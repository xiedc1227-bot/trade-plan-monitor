/* Native bookkeeping tests: no hooks installed, no interpreter required. */
#include "../../scripts/experiments/owner_observer.c"
#define CHECK(value) do { if (!(value)) return __LINE__; } while (0)
static void reset(void) {
 memset(entries,0,sizeof(entries));memset(live,0,sizeof(live));
 memset(domains,0,sizeof(domains));memset(peak,0,sizeof(peak));
 lost=unknown=records=generation=owner=0;
}
static void *fail_realloc(void *ctx,void *p,size_t n) {return NULL;}
int main(void) {
 char storage;void *p=&storage;uint64_t stamp;
 reset();owner=1;add(p,100,0);owner=2;remove_entry(p,0);
 CHECK(live[1]==0 && live[2]==0 && records==0 && !lost);
 reset();owner=1;add(p,100,0);
 CHECK(saved_owner(p,0,&stamp)==1 && stamp);
 owner=2;previous[0].realloc=fail_realloc;
 CHECK(resize(NULL,p,200)==NULL);
 CHECK(live[1]==100 && live[2]==0 && records==1 && !lost);
 /* Old address is freed and reused before its realloc return is recorded. */
 remove_entry(p,0);owner=3;add(p,200,0);
 retire_realloc(p,0,stamp);
 CHECK(lost && live[3]==200 && records==1);
 reset();owner=3;add(p,200,0);retire_realloc(p,0,0);
 CHECK(!lost && unknown==1 && live[3]==200 && records==1);
 reset();owner=1;add(p,100,0);saved_owner(p,0,&stamp);
 retire_realloc(p,0,stamp);owner=1;add(p,200,0);
 CHECK(!lost && live[1]==200 && records==1);
 return 0;
}
