-- docker compose의 db 컨테이너가 빈 볼륨으로 처음 뜰 때 한 번만 실행됩니다.
-- 이미 볼륨이 있으면 실행되지 않지만, tests/conftest.py가 dream_test가 없으면 자동으로 만듭니다.
CREATE DATABASE dream_test OWNER dream;
