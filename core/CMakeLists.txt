cmake_minimum_required(VERSION 3.22)
project(instruments_core LANGUAGES CXX)

# Host-testable core: no Android, no JNI. Units are added one folder at a time.
set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)

if(MSVC)
    add_compile_options(/W4 /WX /permissive- /utf-8)
else()
    add_compile_options(-Wall -Wextra -Wpedantic -Werror)
endif()

enable_testing()

add_subdirectory(testing)
