package io.github.foadsf.instruments.probe

import android.content.Context
import android.content.pm.PackageManager
import android.opengl.EGL14
import android.opengl.EGLConfig
import android.opengl.GLES30
import android.os.Build
import java.io.File

/**
 * Which compute paths the phone advertises. This is inventory, not proof: nothing here runs a
 * kernel. OpenCL in particular is only checked for presence and for being on the vendor's
 * public-library list (what lets an app dlopen it); loading it and verifying results against an
 * fp64 oracle is Stage 5 (android-hpc's backends).
 */
object ComputeFacts {
    fun collect(ctx: Context): Map<String, Any?> = linkedMapOf(
        "gles" to gles(),
        "vulkan" to vulkan(ctx.packageManager),
        "opencl" to openCl(),
        // NNAPI exists from API 27 (always true at minSdk 29) and is deprecated from API 35.
        "nnapi" to mapOf("sdk_int" to Build.VERSION.SDK_INT, "deprecated" to (Build.VERSION.SDK_INT >= 35)),
    )

    private fun vulkan(pm: PackageManager): Map<String, Any?> {
        val features = pm.systemAvailableFeatures.filter { it.name?.startsWith("android.hardware.vulkan") == true }
        return features.associate { f ->
            val v = f.version
            f.name to if (f.name == PackageManager.FEATURE_VULKAN_HARDWARE_VERSION) {
                "${v ushr 22}.${(v ushr 12) and 0x3ff}.${v and 0xfff}"
            } else {
                v
            }
        }
    }

    private fun openCl(): Map<String, Any?> {
        val candidates = listOf("/vendor/lib64/libOpenCL.so", "/system/vendor/lib64/libOpenCL.so", "/system/lib64/libOpenCL.so")
        val publicLists = listOf("/vendor/etc/public.libraries.txt", "/system/etc/public.libraries.txt")
        return linkedMapOf(
            "library_files" to candidates.filter { runCatching { File(it).exists() }.getOrDefault(false) },
            "public_library_entries" to publicLists.associateWith { path ->
                runCatching { File(path).readLines().filter { it.contains("OpenCL", ignoreCase = true) } }
                    .getOrElse { "unreadable: ${it.javaClass.simpleName}" }
            },
            "loaded" to "not attempted (Stage 5)",
        )
    }

    /** GL_RENDERER and GL_VERSION from a throwaway 1x1 off-screen ES 3 context (from parallax). */
    private fun gles(): Map<String, Any?> = runCatching {
        val dpy = EGL14.eglGetDisplay(EGL14.EGL_DEFAULT_DISPLAY)
        val ver = IntArray(2)
        EGL14.eglInitialize(dpy, ver, 0, ver, 1)
        val cfgs = arrayOfNulls<EGLConfig>(1)
        val n = IntArray(1)
        EGL14.eglChooseConfig(dpy, intArrayOf(EGL14.EGL_RENDERABLE_TYPE, 0x40, EGL14.EGL_SURFACE_TYPE,
            EGL14.EGL_PBUFFER_BIT, EGL14.EGL_NONE), 0, cfgs, 0, 1, n, 0)
        val ctx = EGL14.eglCreateContext(dpy, cfgs[0], EGL14.EGL_NO_CONTEXT,
            intArrayOf(EGL14.EGL_CONTEXT_CLIENT_VERSION, 3, EGL14.EGL_NONE), 0)
        val surf = EGL14.eglCreatePbufferSurface(dpy, cfgs[0], intArrayOf(EGL14.EGL_WIDTH, 1, EGL14.EGL_HEIGHT, 1, EGL14.EGL_NONE), 0)
        EGL14.eglMakeCurrent(dpy, surf, surf, ctx)
        val out = mapOf<String, Any?>(
            "renderer" to GLES30.glGetString(GLES30.GL_RENDERER),
            "version" to GLES30.glGetString(GLES30.GL_VERSION),
        )
        EGL14.eglMakeCurrent(dpy, EGL14.EGL_NO_SURFACE, EGL14.EGL_NO_SURFACE, EGL14.EGL_NO_CONTEXT)
        EGL14.eglDestroySurface(dpy, surf)
        EGL14.eglDestroyContext(dpy, ctx)
        out
    }.getOrElse { mapOf("error" to it.toString()) }
}
