# worker/postprocess — 확신도 블러 (이종민)

- 장면 확신도 집계 함수 (11/19), Pillow 블러
- 저장 경로: `scene_blur` (원본은 덮어쓰지 않음)
- 결과와 함께 확신도 단계, 블러 강도, 처리 규격 기록

## 주요 함수

- `aggregate_scene_confidence(elements, scene_element_names=None) -> Confidence`
  - 시각 요소(`person`, `place`, `object`)에 대해 `high=2`, `medium=1`, `low=0`의 평균을 구하고 장면 확신도 단계(`high` >= 1.5, `medium` 0.5~1.5, `low` < 0.5)를 반환합니다.
  - 감정(`emotion`) 요소는 시각 블러 계산에서 제외하되 원본 요소 확신도는 그대로 보존합니다.
  - 상세 내역이 필요하면 `aggregate_scene_confidence_detail(...) -> SceneConfidenceResult`를 사용합니다.
- `apply_confidence_blur(source_path, output_path, confidence_level, settings=None, *, scene_id=None, version_no=None, reuse_existing=False) -> PostprocessResult`
  - 원본 이미지(`original.png`)를 덮어쓰지 않고 `blur_{level}.png`로 별도 저장합니다.
  - 수동 재시도 시 `reuse_existing=True`로 기존에 검증된 후처리 이미지를 재사용할 수 있습니다.
- `postprocess_scene_for_storage(storage_root, dream_id, scene_id, version_no, confidence_level, settings=None, *, reuse_existing=True) -> PostprocessResult`
  - `app.storage.paths` 규칙에 맞춰 상대 경로 기준 후처리를 수행합니다.
