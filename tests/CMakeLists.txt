# ==============================================================================
# REXI Test Suite Targets
# ==============================================================================

add_executable(rexi_unit_tests
    unit/test_version.cpp
    unit/test_events.cpp
    unit/test_spsc_ring_buffer.cpp
    unit/test_simulator_types.cpp
    unit/test_matching_engine.cpp
    unit/test_exchange.cpp
    unit/test_determinism.cpp
    unit/test_market_data_types.cpp
    unit/test_market_data_validation.cpp
    unit/test_market_data_sequence.cpp
    unit/test_market_data_checksum.cpp
    unit/test_market_data_normalizer.cpp
    unit/test_market_data_events.cpp
    unit/test_market_data_determinism.cpp
    unit/test_order_book_types.cpp
    unit/test_order_book_l1_l2.cpp
    unit/test_order_book_l3.cpp
    unit/test_order_book_market_data.cpp
    unit/test_order_book_determinism.cpp
    unit/test_order_pool.cpp
    unit/test_order_id_index.cpp
    unit/test_order_book_capacity.cpp
    unit/test_order_book_allocation.cpp
    integration/test_event_concurrency.cpp
    integration/test_exchange_scenario.cpp
    integration/test_market_data_integration.cpp
    integration/test_order_book_pipeline.cpp
)

target_link_libraries(rexi_unit_tests PRIVATE
    rexi_core
    rexi_simulator
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
