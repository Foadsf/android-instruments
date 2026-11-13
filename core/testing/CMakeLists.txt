add_library(instruments_testing STATIC check_main.cpp)
target_include_directories(instruments_testing PUBLIC ${CMAKE_CURRENT_SOURCE_DIR}/include)

# instruments_add_test(<name> <sources...>): a test that must pass.
function(instruments_add_test name)
    add_executable(${name} ${ARGN})
    target_link_libraries(${name} PRIVATE instruments_testing)
    add_test(NAME ${name} COMMAND ${name})
endfunction()

# instruments_add_negative_control(<name> <sources...>): a test that must FAIL. ctest reports it
# as passed only when the binary exits non-zero.
function(instruments_add_negative_control name)
    instruments_add_test(${name} ${ARGN})
    set_tests_properties(${name} PROPERTIES WILL_FAIL TRUE LABELS negative_control)
endfunction()

instruments_add_test(test_check tests/test_check.cpp)
instruments_add_negative_control(negative_control_false_check tests/negative_control_false_check.cpp)
instruments_add_negative_control(negative_control_nan_near tests/negative_control_nan_near.cpp)
instruments_add_negative_control(negative_control_empty_suite tests/negative_control_empty_suite.cpp)
