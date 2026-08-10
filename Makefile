build:
	docker compose -f local.yml up --build -d --remove-orphans

build-api:
	docker compose -f local.yml up --build -d api

up:
	docker compose -f local.yml up -d

down:
	docker compose -f local.yml down

down-v:
	docker compose -f local.yml down -v

ledgr-config:
	docker compose -f local.yml config

makemigrations:
	docker compose -f local.yml exec -it -u 0  api alembic revision --autogenerate -m "$(name)"

migrate:
	docker compose -f local.yml exec -it -u 0  api alembic upgrade head

history:
	docker compose -f local.yml exec -it api alembic history

current-migration:
	docker compose -f local.yml exec -it api alembic current

downgrade:
	docker compose -f local.yml exec -it api alembic downgrade $(version)

inspect-network:
	docker network inspect ledgr_local_network

psql:
	docker compose -f local.yml exec -it postgres psql -U pranto -d ledgr
