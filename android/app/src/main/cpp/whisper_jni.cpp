#include <jni.h>
#include <string>
#include <android/log.h>
#include <vector>
#include "whisper.h"

#define LOG_TAG "WhisperJNI"
#define LOGI(...) __android_log_print(ANDROID_LOG_INFO,  LOG_TAG, __VA_ARGS__)
#define LOGE(...) __android_log_print(ANDROID_LOG_ERROR, LOG_TAG, __VA_ARGS__)

static whisper_context* g_ctx = nullptr;

extern "C" {

JNIEXPORT jboolean JNICALL
Java_com_intelliverse_whisperyoutube_WhisperEngine_loadModel(
        JNIEnv* env, jobject, jstring modelPath) {
    const char* path = env->GetStringUTFChars(modelPath, nullptr);
    LOGI("Loading model: %s", path);
    struct whisper_context_params p = whisper_context_default_params();
    p.use_gpu = false;
    g_ctx = whisper_init_from_file_with_params(path, p);
    env->ReleaseStringUTFChars(modelPath, path);
    bool ok = (g_ctx != nullptr);
    LOGI("Model loaded: %d", ok);
    return ok;
}

JNIEXPORT jstring JNICALL
Java_com_intelliverse_whisperyoutube_WhisperEngine_transcribeAudio(
        JNIEnv* env, jobject, jfloatArray pcmData) {
    if (!g_ctx) {
        return env->NewStringUTF("[Error] Model not loaded");
    }
    jsize n = env->GetArrayLength(pcmData);
    jfloat* samples = env->GetFloatArrayElements(pcmData, nullptr);

    whisper_full_params params = whisper_full_default_params(WHISPER_SAMPLING_GREEDY);
    params.n_threads        = 4;
    params.language         = "auto";
    params.translate        = false;
    params.print_progress   = false;
    params.print_realtime   = false;
    params.print_timestamps = false;

    int rc = whisper_full(g_ctx, params, samples, (int)n);
    env->ReleaseFloatArrayElements(pcmData, samples, 0);

    if (rc != 0) {
        return env->NewStringUTF("[Error] Transcription failed");
    }

    std::string result;
    int nseg = whisper_full_n_segments(g_ctx);
    for (int i = 0; i < nseg; i++) {
        const char* txt = whisper_full_get_segment_text(g_ctx, i);
        if (txt) result += txt;
    }
    return env->NewStringUTF(result.c_str());
}

JNIEXPORT void JNICALL
Java_com_intelliverse_whisperyoutube_WhisperEngine_releaseModel(
        JNIEnv*, jobject) {
if (g_ctx) {
whisper_free(g_ctx);
g_ctx = nullptr;
LOGI("Model released");
}
}

} // extern "C"