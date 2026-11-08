"""파일 저장 경로 규칙 (docs/rules/file-paths.md). DB에는 STORAGE_ROOT 기준 상대 경로를 저장한다."""
from pathlib import PurePosixPath


def audio(dream_id: int, audio_id: int, ext: str) -> PurePosixPath:
    return PurePosixPath(f"dreams/{dream_id}/audio/{audio_id}.{ext}")


def _scene_dir(dream_id: int, scene_id: int, version_no: int) -> PurePosixPath:
    return PurePosixPath(f"dreams/{dream_id}/scenes/{scene_id}/v{version_no}")


def scene_original(dream_id: int, scene_id: int, version_no: int) -> PurePosixPath:
    return _scene_dir(dream_id, scene_id, version_no) / "original.png"


def scene_blur(dream_id: int, scene_id: int, version_no: int, level: str) -> PurePosixPath:
    return _scene_dir(dream_id, scene_id, version_no) / f"blur_{level}.png"


def scene_narration(dream_id: int, scene_id: int, version_no: int) -> PurePosixPath:
    return _scene_dir(dream_id, scene_id, version_no) / "narration.mp3"


def render_video(dream_id: int, render_id: int) -> PurePosixPath:
    return PurePosixPath(f"dreams/{dream_id}/renders/{render_id}/video.mp4")


def job_tmp(job_id: int) -> PurePosixPath:
    return PurePosixPath(f"tmp/{job_id}")


def public_url(rel_path: PurePosixPath | str) -> str:
    return f"/storage/{rel_path}"
