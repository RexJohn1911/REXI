# ==============================================================================
# REXI Test Suite Targets
# ==============================================================================

add_executable(rexi_unit_tests
    unit/test_version.cpp
)

target_link_libraries(rexi_unit_tests PRIVATE
    rexi_core
    GTest::gtest_main
)

target_compile_features(rexi_unit_tests PRIVATE cxx_std_20)

include(GoogleTest)
gtest_discover_tests(rexi_unit_tests)
