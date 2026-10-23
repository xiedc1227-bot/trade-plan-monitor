// Diagnostic Rust-domain accounting only. Not an admission allocator.
use std::alloc::{GlobalAlloc, Layout, System};
use std::sync::atomic::{AtomicUsize, Ordering::SeqCst};

static LIVE: AtomicUsize = AtomicUsize::new(0);
static PEAK: AtomicUsize = AtomicUsize::new(0);
static CALLS: AtomicUsize = AtomicUsize::new(0);
static LOST: AtomicUsize = AtomicUsize::new(0);

fn charge(n: usize) {
    if let Ok(old) = LIVE.fetch_update(SeqCst, SeqCst, |v| v.checked_add(n)) {
        PEAK.fetch_max(old + n, SeqCst);
    } else {
        LOST.store(1, SeqCst);
    }
}
fn release(n: usize) {
    if LIVE.fetch_update(SeqCst, SeqCst, |v| v.checked_sub(n)).is_err() {
        LOST.store(1, SeqCst);
    }
}
struct Observer;
unsafe impl GlobalAlloc for Observer {
    unsafe fn alloc(&self, layout: Layout) -> *mut u8 {
        CALLS.fetch_add(1, SeqCst);
        charge(layout.size());
        let p = unsafe { System.alloc(layout) };
        if p.is_null() { release(layout.size()); }
        p
    }
    unsafe fn alloc_zeroed(&self, layout: Layout) -> *mut u8 {
        CALLS.fetch_add(1, SeqCst);
        charge(layout.size());
        let p = unsafe { System.alloc_zeroed(layout) };
        if p.is_null() { release(layout.size()); }
        p
    }
    unsafe fn dealloc(&self, p: *mut u8, layout: Layout) {
        unsafe { System.dealloc(p, layout) };
        release(layout.size());
    }
    unsafe fn realloc(&self, p: *mut u8, layout: Layout, new_size: usize) -> *mut u8 {
        CALLS.fetch_add(1, SeqCst);
        // Count possible old/new coexistence before calling the backing allocator.
        charge(new_size);
        let next = unsafe { System.realloc(p, layout, new_size) };
        release(if next.is_null() { new_size } else { layout.size() });
        next
    }
}
#[global_allocator]
static ALLOCATOR: Observer = Observer;

#[unsafe(no_mangle)]
pub extern "C" fn tpm_allocation_stat(index: usize) -> usize {
    match index {
        0 => LIVE.load(SeqCst),
        1 => PEAK.load(SeqCst),
        2 => CALLS.load(SeqCst),
        _ => LOST.load(SeqCst),
    }
}
