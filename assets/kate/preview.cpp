// Kate glass theme preview — this is a disposable copy.
// Scroll, select text, resize, and try editing/undoing.
// Your normal documents and Kate settings are not used here.

#include <array>
#include <iostream>
#include <string_view>

struct ThemeColor {
    std::string_view name;
    double opacity;
};

constexpr auto surfaces = std::array {
    ThemeColor{"light: icy white and pale blue", 0.10},
    ThemeColor{"dark: black with shaded panels", 0.10},
    ThemeColor{"balanced editor backing", 0.64},
};

int main()
{
    for (const auto &surface : surfaces) {
        std::cout << surface.name << ": " << surface.opacity << '\n';
    }
    return 0;
}

// A long line should wrap without changing the overall effect: headings, numbers, strings, comments and normal text all need to stay readable while the background remains visibly translucent.

namespace examples {
constexpr int square(int value) { return value * value; }
constexpr int clamp(int value, int low, int high)
{
    if (value < low) return low;
    if (value > high) return high;
    return value;
}

struct Note {
    std::string_view title;
    bool pinned = false;
};

constexpr auto notes = std::array {
    Note{"Theme colors stay opaque", true},
    Note{"Backgrounds can be translucent", false},
    Note{"This file is safe to experiment with", false},
};

void print_notes()
{
    for (const auto &[title, pinned] : notes) {
        std::cout << (pinned ? "* " : "- ") << title << '\n';
    }
}
} // namespace examples

// More lines for a real scroll test.
constexpr int sample_01 = examples::square(1);
constexpr int sample_02 = examples::square(2);
constexpr int sample_03 = examples::square(3);
constexpr int sample_04 = examples::square(4);
constexpr int sample_05 = examples::square(5);
constexpr int sample_06 = examples::square(6);
constexpr int sample_07 = examples::square(7);
constexpr int sample_08 = examples::square(8);
constexpr int sample_09 = examples::square(9);
constexpr int sample_10 = examples::square(10);

// Reach the end, then return to the top and check the repaint.
// Any changes you save here belong to this temporary preview, not the repository.
