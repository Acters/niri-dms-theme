cmake_minimum_required(VERSION 3.22)
project(katebalancedglassplugin VERSION 0.1.0 LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_AUTOMOC ON)

find_package(Qt6 REQUIRED COMPONENTS Widgets)
find_package(KF6TextEditor 6.31 REQUIRED)
find_package(KF6CoreAddons REQUIRED)
find_package(KF6Config REQUIRED)

add_library(katebalancedglassplugin MODULE balancedglassplugin.cpp)
set_target_properties(katebalancedglassplugin PROPERTIES PREFIX "")
target_link_libraries(katebalancedglassplugin PRIVATE
    KF6::TextEditor KF6::CoreAddons KF6::ConfigCore Qt6::Widgets)

# Deliberately no install rule: choose an explicit personal Qt plugin root.
