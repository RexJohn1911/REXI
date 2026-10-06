#include "allocation_guard.hpp"

#include <cstdlib>
#include <new>

namespace rexi::test {

std::atomic<size_t> g_alloc_count{0};
std::atomic<bool> g_track_allocations{false};

ScopedAllocationGuard::ScopedAllocationGuard() {
    g_alloc_count.store(0, std::memory_order_seq_cst);
    g_track_allocations.store(true, std::memory_order_seq_cst);
}

ScopedAllocationGuard::~ScopedAllocationGuard() {
    g_track_allocations.store(false, std::memory_order_seq_cst);
}

size_t ScopedAllocationGuard::allocations() const noexcept {
    return g_alloc_count.load(std::memory_order_seq_cst);
}

}  // namespace rexi::test

void* operator new(std::size_t size) {
    if (rexi::test::g_track_allocations.load(std::memory_order_relaxed)) {
        rexi::test::g_alloc_count.fetch_add(1, std::memory_order_relaxed);
    }
    void* ptr = std::malloc(size);
    if (ptr == nullptr) {
        throw std::bad_alloc();
    }
    return ptr;
}

void operator delete(void* ptr) noexcept {
    std::free(ptr);
}

void operator delete(void* ptr, std::size_t /*unused*/) noexcept {
    std::free(ptr);
}

void* operator new[](std::size_t size) {
    if (rexi::test::g_track_allocations.load(std::memory_order_relaxed)) {
        rexi::test::g_alloc_count.fetch_add(1, std::memory_order_relaxed);
    }
    void* ptr = std::malloc(size);
    if (ptr == nullptr) {
        throw std::bad_alloc();
    }
    return ptr;
}

void operator delete[](void* ptr) noexcept {
    std::free(ptr);
}

void operator delete[](void* ptr, std::size_t /*unused*/) noexcept {
    std::free(ptr);
}
