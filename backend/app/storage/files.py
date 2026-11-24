"""/storage 파일 제공.

Starlette StaticFiles 마운트다. 경로 정규화와 storage 밖 탈출 검사는 StaticFiles가 하고,
그 검사가 끝난 경로가 storage/eval/ 아래의 key.json이면 파일을 주지 않는다.
요청 문자열 검사에 더해, 실제로 찾은 파일을 realpath로 풀어 같은 파일이면 역시 주지 않는다.
없는 파일과 같은 404(오류 형식)라서, 정답 파일이 있는지는 응답으로 알 수 없다.
"""

import errno
import os
import stat

import anyio
from starlette.exceptions import HTTPException
from starlette.responses import Response
from starlette.staticfiles import StaticFiles
from starlette.types import Scope

from app.core.errors import NotFound


def is_eval_answer_key(normalized: str) -> bool:
    """normpath·realpath가 접은 상대 경로가 eval 아래의 key.json인지. 대소문자는 가리지 않는다."""
    parts = [part for part in normalized.replace("\\", "/").split("/") if part not in ("", ".")]
    if not parts or ".." in parts:
        return False
    return parts[0].casefold() == "eval" and parts[-1].casefold() == "key.json"


class StorageFiles(StaticFiles):
    async def get_response(self, path: str, scope: Scope) -> Response:
        if scope["method"] not in ("GET", "HEAD"):
            raise HTTPException(status_code=405, headers={"Allow": "GET, HEAD"})

        try:
            full_path, stat_result = await anyio.to_thread.run_sync(self.lookup_path, path)
        except PermissionError:
            raise HTTPException(status_code=401) from None
        except OSError as exc:
            if exc.errno == errno.ENAMETOOLONG:
                raise NotFound("파일을 찾을 수 없습니다.") from None
            raise
        except ValueError:
            raise NotFound("파일을 찾을 수 없습니다.") from None

        # path는 요청을 normpath한 문자열이다. 그 검사는 그대로 둔다.
        # full_path는 StaticFiles가 찾은 파일이다. realpath로 풀어 끝 점·공백·ADS·8.3 이름도 걸러낸다.
        relative = self._relative_inside(full_path) if full_path else ""
        if is_eval_answer_key(path) or is_eval_answer_key(relative) or self._opened_file_is_eval_key(full_path):
            raise NotFound("파일을 찾을 수 없습니다.")

        if stat_result and stat.S_ISREG(stat_result.st_mode):
            return self.file_response(full_path, stat_result, scope)
        raise NotFound("파일을 찾을 수 없습니다.")

    def _opened_file_is_eval_key(self, full_path: str) -> bool:
        """찾아낸 파일을 realpath로 풀었을 때 storage/eval/ 아래의 key.json이면 True."""
        if not full_path:
            return False
        relative = self._relative_inside(os.path.realpath(full_path))
        parts = [part for part in relative.replace("\\", "/").split("/") if part not in ("", ".")]
        if len(parts) < 2 or ".." in parts:
            return False
        return parts[0].lower() == "eval" and parts[-1].lower() == "key.json"

    def _relative_inside(self, full_path: str) -> str:
        """탈출 검사를 통과한 절대 경로를 storage 기준 상대 경로로 되돌린다. 밖이면 빈 문자열."""
        for directory in self.all_directories:
            root = os.path.realpath(directory)
            try:
                if os.path.commonpath([full_path, root]) != str(root):
                    continue
            except ValueError:
                continue
            return os.path.relpath(full_path, root)
        return ""
