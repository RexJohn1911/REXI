# ==============================================================================
# REXI Test Suite Targets
# ==============================================================================

add_executable(rexi_unit_tests
    unit/test_version.cpp
    unit/test_events.cpp
    unit/test_spsc_ring_buffer.cpp
    integration/test_event_concurrency.cpp
)

target_link_libraries(rexi_unit_tests PRIVATE
    rexi_core
    GTest::gtest_main
)

target_compile_features(rexi_unit_tests PRIVATE cxx_std_20)

if(CMAKE_CXX_COMPILER_ID MATCHES "Clang|AppleClang|GNU")
    target_compile_options(rexi_unit_tests PRIVATE
        -Wall
        -Wextra
        -Wpedantic
        -Wconversion
        -Wsign-conversion
        -Wshadow
        -Wnon-virtual-dtor
    )
endif()

include(GoogleTest)
gtest_discover_tests(rexi_unit_tests)
