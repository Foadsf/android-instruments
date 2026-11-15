set(ALIGN_SOURCES align.c align_image.c align_math.c)

add_library(instruments_align STATIC ${ALIGN_SOURCES})
target_include_directories(instruments_align PUBLIC ${CMAKE_CURRENT_SOURCE_DIR}/include
                                             PRIVATE ${CMAKE_CURRENT_SOURCE_DIR})

# Test-only build of the same method with bilinear sampling, for its negative control.
add_library(instruments_align_bilinear STATIC ${ALIGN_SOURCES})
target_include_directories(instruments_align_bilinear PUBLIC ${CMAKE_CURRENT_SOURCE_DIR}/include
                                                      PRIVATE ${CMAKE_CURRENT_SOURCE_DIR})
target_compile_definitions(instruments_align_bilinear PRIVATE ALIGN_TEST_BILINEAR)

if(NOT MSVC)
    target_link_libraries(instruments_align PUBLIC m)
    target_link_libraries(instruments_align_bilinear PUBLIC m)
endif()

add_executable(align_cli cli/align_cli.cpp)
target_link_libraries(align_cli PRIVATE instruments_align)

instruments_add_test(test_align tests/test_align.cpp)
target_link_libraries(test_align PRIVATE instruments_align)

instruments_add_negative_control(negative_control_align_sign tests/negative_control_sign.cpp)
target_link_libraries(negative_control_align_sign PRIVATE instruments_align)

instruments_add_negative_control(negative_control_align_identity tests/negative_control_identity.cpp)
target_link_libraries(negative_control_align_identity PRIVATE instruments_align)

# The bilinear control did NOT fail on 2026-11-15 (RMS 0.003 px, same as bicubic): built as a plain
# executable, not registered, until the contract decides (align.md, "Build state").
add_executable(negative_control_align_bilinear tests/negative_control_bilinear.cpp)
target_link_libraries(negative_control_align_bilinear PRIVATE instruments_align_bilinear instruments_testing)
