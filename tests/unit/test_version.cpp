#include "rexi/version.hpp"

#include <gtest/gtest.h>

namespace rexi::tests {

TEST(VersionTest, SemanticVersionComponents) {
    constexpr auto ver = rexi::get_version();
    EXPECT_EQ(ver.major, 0U);
    EXPECT_EQ(ver.minor, 1U);
    EXPECT_EQ(ver.patch, 0U);
    EXPECT_EQ(ver.suffix, "dev");
}

TEST(VersionTest, VersionStringNotEmpty) {
    const auto ver_str = rexi::get_version_string();
    EXPECT_FALSE(ver_str.empty());
    EXPECT_EQ(ver_str, "0.1.0-dev");
}

TEST(VersionTest, BuildInfoValid) {
    const auto build_info = rexi::get_build_info();
    EXPECT_FALSE(build_info.empty());
}

}  // namespace rexi::tests
