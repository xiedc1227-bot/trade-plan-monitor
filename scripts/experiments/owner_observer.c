/* Disposable-process logical allocation observer. Not an admission allocator.
 * Never uninstall: allocator callbacks remain live until process exit.
 * Unknown pre-install frees and table loss invalidate complete ownership claims. */
#define PY_SSIZE_T_CLEAN
#include <Python.h>
#include <windows.h>
#include <stdint.h>

#define CAP 262144
#define OWNERS 16
typedef struct { void *p; size_t size; uint64_t generation; unsigned domain, owner, state; } Entry;
static Entry entries[CAP];
static SRWLOCK lock = SRWLOCK_INIT;
static size_t live[OWNERS], peak[OWNERS], lost, unknown, records;
static size_t domains[5];
static uint64_t generation;
static __declspec(thread) unsigned owner;
static PyMemAllocatorEx previous[3];
static PyObjectArenaAllocator arena;
static int installed;

static void add(void *p, size_t n, unsigned domain) {
    if (!p) return;
    size_t i = (((uintptr_t)p >> 4) ^ domain) % CAP, free_slot = CAP;
    AcquireSRWLockExclusive(&lock);
    if(lost) goto done;
    for (size_t step=0; step<CAP; step++, i=(i+1)%CAP) {
        Entry *e=&entries[i];
        if (e->state==1 && e->p==p && e->domain==domain) { lost++; goto done; }
        if (e->state!=1 && free_slot==CAP) free_slot=i;
        if (!e->state) break;
    }
    if (free_slot==CAP || SIZE_MAX-live[owner]<n || SIZE_MAX-domains[domain]<n
        || generation==UINT64_MAX) { lost++; goto done; }
    entries[free_slot]=(Entry){p,n,++generation,domain,owner,1};
    live[owner]+=n; domains[domain]+=n; records++;
    if (live[owner]>peak[owner]) peak[owner]=live[owner];
done:
    ReleaseSRWLockExclusive(&lock);
}
static void remove_checked(void *p, unsigned domain, uint64_t expected) {
    if (!p) return;
    size_t i=(((uintptr_t)p>>4)^domain)%CAP;
    AcquireSRWLockExclusive(&lock);
    if(lost) goto done;
    for (size_t step=0; step<CAP; step++,i=(i+1)%CAP) {
        Entry *e=&entries[i];
        if (!e->state) break;
        if (e->state==1 && e->p==p && e->domain==domain) {
            if(expected && e->generation!=expected) {lost++;goto done;}
            live[e->owner]-=e->size; domains[domain]-=e->size; e->state=2; records--; goto done;
        }
    }
    if(expected) lost++; else unknown++;
done:
    ReleaseSRWLockExclusive(&lock);
}
static void remove_entry(void *p,unsigned domain) {remove_checked(p,domain,0);}
static unsigned saved_owner(void *p,unsigned domain,uint64_t *stamp) {
    unsigned result=owner;
    *stamp=0;
    size_t i=(((uintptr_t)p>>4)^domain)%CAP;
    AcquireSRWLockExclusive(&lock);
    if(lost) {ReleaseSRWLockExclusive(&lock);return result;}
    for(size_t step=0;step<CAP;step++,i=(i+1)%CAP) {
        Entry *e=&entries[i]; if(!e->state)break;
        if(e->state==1 && e->p==p && e->domain==domain){result=e->owner;*stamp=e->generation;break;}
    }
    ReleaseSRWLockExclusive(&lock);return result;
}
static void retire_realloc(void *p,unsigned domain,uint64_t stamp) {
    if(stamp) remove_checked(p,domain,stamp);
    else if(p) {
        AcquireSRWLockExclusive(&lock);unknown++;ReleaseSRWLockExclusive(&lock);
    }
}
static void *allocate(void *ctx, size_t n) {
    unsigned d=(unsigned)(uintptr_t)ctx;
    void *p=previous[d].malloc(previous[d].ctx,n); add(p,n,d); return p;
}
static void *zeroed(void *ctx,size_t n,size_t size) {
    unsigned d=(unsigned)(uintptr_t)ctx;
    void *p=previous[d].calloc(previous[d].ctx,n,size);
    if (size && n>SIZE_MAX/size) { if(p) {
        AcquireSRWLockExclusive(&lock);lost++;ReleaseSRWLockExclusive(&lock);
    } }
    else add(p,n*size,d);
    return p;
}
static void release(void *ctx,void *p) {
    unsigned d=(unsigned)(uintptr_t)ctx;
    remove_entry(p,d); previous[d].free(previous[d].ctx,p);
}
static void *resize(void *ctx,void *p,size_t n) {
    unsigned d=(unsigned)(uintptr_t)ctx;
    /* Post-call tracking cannot bound backing realloc coexistence. Explicitly
       unqualified; preserve allocator failure semantics and the old entry. */
    uint64_t stamp;
    unsigned original=saved_owner(p,d,&stamp), current=owner;
    void *next=previous[d].realloc(previous[d].ctx,p,n);
    if(next) { retire_realloc(p,d,stamp); owner=original; add(next,n,d); owner=current; }
    return next;
}
static void *arena_alloc(void *ctx,size_t n) {
    void *p=arena.alloc(arena.ctx,n); add(p,n,3); return p;
}
static void arena_free(void *ctx,void *p,size_t n) {
    remove_entry(p,3); arena.free(arena.ctx,p,n);
}

typedef struct {
 void *(*malloc_fn)(int); void (*free_fn)(void*); void *(*realloc_fn)(void*,int);
 int (*size_fn)(void*); int (*round_fn)(int); int (*init_fn)(void*);
 void (*shutdown_fn)(void*); void *ctx;
} SqlMethods;
static SqlMethods sql;
static HMODULE sqlite;
static void *sql_alloc(int n) { void*p=sql.malloc_fn(n); add(p,p?(size_t)sql.size_fn(p):0,4); return p; }
static void sql_free(void*p) { remove_entry(p,4); sql.free_fn(p); }
static void *sql_resize(void*p,int n) {
 uint64_t stamp;
 unsigned original=saved_owner(p,4,&stamp),current=owner;
 void*q=sql.realloc_fn(p,n); if(q){retire_realloc(p,4,stamp);owner=original;
 add(q,(size_t)sql.size_fn(q),4);owner=current;} return q;
}
static PyObject *install(PyObject*self,PyObject*args) {
    const wchar_t *path; PyObject *path_obj;
    if(!PyArg_ParseTuple(args,"U",&path_obj)) return NULL;
    if(installed) return PyErr_Format(PyExc_RuntimeError,"already installed");
    path=PyUnicode_AsWideCharString(path_obj,NULL); if(!path)return NULL;
    sqlite=LoadLibraryW(path); PyMem_Free((void*)path);
    if(!sqlite)return PyErr_Format(PyExc_RuntimeError,"SQLite load failed");
    typedef int (__cdecl *Config)(int,...);
    Config config=(Config)GetProcAddress(sqlite,"sqlite3_config");
    if(!config)return PyErr_Format(PyExc_RuntimeError,"SQLite config unavailable");
    int rc=config(5,&sql);
    if(rc)return PyErr_Format(PyExc_RuntimeError,"SQLite GETMALLOC: %d",rc);
    SqlMethods wrapped=sql;
    wrapped.malloc_fn=sql_alloc;wrapped.free_fn=sql_free;wrapped.realloc_fn=sql_resize;
    rc=config(4,&wrapped);
    if(rc)return PyErr_Format(PyExc_RuntimeError,"SQLite MALLOC: %d",rc);
    for(unsigned d=0;d<3;d++) {
        PyMem_GetAllocator((PyMemAllocatorDomain)d,&previous[d]);
        PyMemAllocatorEx w={(void*)(uintptr_t)d,allocate,zeroed,resize,release};
        PyMem_SetAllocator((PyMemAllocatorDomain)d,&w);
    }
    PyObject_GetArenaAllocator(&arena);
    PyObjectArenaAllocator a={NULL,arena_alloc,arena_free}; PyObject_SetArenaAllocator(&a);
    installed=1; Py_RETURN_NONE;
}
static PyObject *set_owner(PyObject*self,PyObject*arg) {
    unsigned long value=PyLong_AsUnsignedLong(arg); if(PyErr_Occurred())return NULL;
    if(value>=OWNERS)return PyErr_Format(PyExc_ValueError,"owner out of range");
    owner=(unsigned)value; Py_RETURN_NONE;
}
static PyObject *snapshot(PyObject*self,PyObject*args) {
    size_t l[OWNERS],p[OWNERS],ds[5],lost_copy,unknown_copy,count;
    AcquireSRWLockExclusive(&lock);
    memcpy(l,live,sizeof(l));memcpy(p,peak,sizeof(p));
    memcpy(ds,domains,sizeof(ds));
    lost_copy=lost;unknown_copy=unknown;count=records;
    ReleaseSRWLockExclusive(&lock);
    PyObject *ls=PyList_New(OWNERS),*ps=PyList_New(OWNERS);
    if(!ls||!ps){Py_XDECREF(ls);Py_XDECREF(ps);return NULL;}
    for(int i=0;i<OWNERS;i++){PyObject*a=PyLong_FromSize_t(l[i]),*b=PyLong_FromSize_t(p[i]);
      if(!a||!b){Py_XDECREF(a);Py_XDECREF(b);Py_DECREF(ls);Py_DECREF(ps);return NULL;}
      PyList_SET_ITEM(ls,i,a);PyList_SET_ITEM(ps,i,b);}
    return Py_BuildValue("{s:N,s:N,s:(KKKKK),s:K,s:K,s:K,s:K}","live",ls,"peak",ps,
      "domains",(unsigned long long)ds[0],(unsigned long long)ds[1],
      (unsigned long long)ds[2],(unsigned long long)ds[3],(unsigned long long)ds[4],
      "lost",(unsigned long long)lost_copy,"unknown",(unsigned long long)unknown_copy,
      "records",(unsigned long long)count,"tableBytes",(unsigned long long)sizeof(entries));
}
static PyObject *raw_alloc(PyObject*self,PyObject*arg) {
    size_t n=PyLong_AsSize_t(arg);if(PyErr_Occurred())return NULL;
    void*p=PyMem_RawMalloc(n);if(!p)return PyErr_NoMemory();
    PyObject *result=PyLong_FromVoidPtr(p);if(!result)PyMem_RawFree(p);return result;
}
static PyObject *raw_free(PyObject*self,PyObject*arg) {
    void*p=PyLong_AsVoidPtr(arg);if(PyErr_Occurred())return NULL;
    PyMem_RawFree(p);Py_RETURN_NONE;
}
static PyMethodDef methods[]={
 {"install",install,METH_VARARGS,NULL},{"owner",set_owner,METH_O,NULL},
 {"snapshot",snapshot,METH_NOARGS,NULL},{"raw_alloc",raw_alloc,METH_O,NULL},
 {"raw_free",raw_free,METH_O,NULL},{NULL,NULL,0,NULL}};
static struct PyModuleDef module={PyModuleDef_HEAD_INIT,"owner_observer",NULL,-1,methods};
PyMODINIT_FUNC PyInit_owner_observer(void){return PyModule_Create(&module);}
