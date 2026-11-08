# worker/render — FFmpeg 렌더링 (이종민), TTS 나레이션 (김민진)

- 렌더링: `render_video` 작업 함수 (11/17)
  - 처리 단계: validating_input → postprocessing → composing → verifying
  - 출력 규격(초안): 1280×720, 30fps, MP4
  - 저장 경로: `render_video`, 임시 파일은 `job_tmp`
- TTS(선택): `generate_narration` 작업 함수, 저장 경로 `scene_narration`
