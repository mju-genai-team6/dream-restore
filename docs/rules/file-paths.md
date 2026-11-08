# 파일 경로 규칙

코드 원본: `backend/app/storage/paths.py`

생성 결과물은 저장소 루트의 `storage/` 아래에 저장하며 Git에 올리지 않습니다.
DB에는 `storage/` 기준 상대 경로를 저장하고, API 응답에는 `/storage/...` 주소를 줍니다.

```
storage/dreams/{dreamId}/audio/{audioId}.webm|mp4
storage/dreams/{dreamId}/scenes/{sceneId}/v{versionNo}/original.png
storage/dreams/{dreamId}/scenes/{sceneId}/v{versionNo}/blur_{level}.png
storage/dreams/{dreamId}/scenes/{sceneId}/v{versionNo}/narration.mp3
storage/dreams/{dreamId}/renders/{renderId}/video.mp4
storage/tmp/{jobId}/          작업 중 임시 파일, 검증 후 위 경로로 이동
```

- 원본 이미지는 덮어쓰지 않습니다. 수정은 새 버전 폴더(`v2`, `v3`...)로 저장합니다.
- 실험 결과물은 각 실험 폴더의 `outputs/`에 저장합니다 (Git 제외).
