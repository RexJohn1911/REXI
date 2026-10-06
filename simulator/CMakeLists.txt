# ==============================================================================
# REXI Simulator Library Target (Phase 03 Exchange Simulator)
# ==============================================================================

add_library(rexi_simulator STATIC
    src/simulator.cpp
)

target_include_directories(rexi_simulator
    PUBLIC
        $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/include>
        $<INSTALL_INTERFACE:include>
)

target_link_libraries(rexi_simulator
    PUBLIC
        rexi_core
)

target_compile_features(rexi_simulator PUBLIC cxx_std_20)

if(CMAKE_CXX_COMPILER_ID MATCHES "Clang|AppleClang|GNU")
    target_compile_options(rexi_simulator PRIVATE
        -Wall
        -Wextra
        -Wpedantic
        -Wconversion
        -Wsign-conversion
        -Wshadow
        -Wnon-virtual-dtor
    )
endif()
