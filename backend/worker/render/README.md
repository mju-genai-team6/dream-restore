# worker/render — FFmpeg 렌더링 (이종민), TTS 나레이션 (김민진)

- 렌더링: `render_video` 작업 함수 (11/17)
  - 처리 단계: `validating_input` → `postprocessing` → `composing` → `verifying`
  - 출력 규격(초안): 1280×720, 30fps, MP4
  - 저장 경로: `render_video`, 임시 파일은 `job_tmp`
- TTS(선택): `generate_narration` 작업 함수, 저장 경로 `scene_narration`

## 구현 모듈 (E1 렌더링)

- `worker.render.video`:
  - `compose_slideshow_video(scenes, output_path, settings=None, ...)`: Ken Burns 확대·이동(`zoompan`), 장면 간 부드러운 전환(`xfade`), 비율 보정 여백(`pad`), 선택적 나레이션 오디오 결합(`adelay` + `amix`)을 적용해 MP4 영상을 합성합니다.
  - `verify_rendered_video(video_path, ...)`: 출력 파일 존재, 스트림 디코딩 가능 여부, 해상도(`1280×720`), 재생 길이를 검증합니다.
- `worker.render.handler`:
  - `handle_render_video(ctx, payload)`: `JobType.RENDER_VIDEO` 핸들러로 등록되어 4단계 진행 보고, 장면 버전 고정, 후처리 이미지 재사용, 임시 폴더 합성 후 최종 경로 이동을 수행합니다.
