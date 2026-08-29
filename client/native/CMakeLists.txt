cmake_minimum_required(VERSION 3.14)
project(libvoice_engine VERSION 1.0.0 LANGUAGES C)

set(CMAKE_C_STANDARD 11)
set(CMAKE_C_STANDARD_REQUIRED ON)

# Source and Include files
set(SOURCE_FILES
    libvoice_engine.c
)

set(HEADER_FILES
    libvoice_engine.h
)

# Shared library target
add_library(voice_engine SHARED
    ${SOURCE_FILES}
    ${HEADER_FILES}
)

target_include_directories(voice_engine PUBLIC
    ${CMAKE_CURRENT_SOURCE_DIR}
)

if (WIN32)
    target_compile_definitions(voice_engine PRIVATE _CRT_SECURE_NO_WARNINGS)
    set_target_properties(voice_engine PROPERTIES
        OUTPUT_NAME "voice_engine"
        PREFIX ""
    )
else()
    target_link_libraries(voice_engine PRIVATE m)
    set_target_properties(voice_engine PROPERTIES
        OUTPUT_NAME "voice_engine"
    )
endif()
