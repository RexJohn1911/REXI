#include "rexi/version.hpp"

namespace rexi {

std::string_view get_version_string() noexcept {
    return "0.1.0-dev";
}

std::string_view get_build_info() noexcept {
#ifdef __clang__
    return "Clang C++20 (Portable Target)";
#elif defined(__GNUC__)
    return "GCC C++20 (Portable Target)";
#else
    return "Standard C++20";
#endif
}

}  // namespace rexi
