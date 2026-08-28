## Docker

### Create docker network

```
docker network create ledgr_local_network
```

### Checking whether compose file gets all the environment variables

```
docker compose -f local.yml config
```

### Building the docker compose

```
docker compose -f local.yml up --build -d --remove-orphans
```

### Bringing down all containers

```
docker compose -f local.yml down
```

#### With volumes

```
docker compose -f local.yml down -v
```

## Database

### Initialize Alembic with async template

```
alembic init -t async migrations
```

### Creating database migrations

```
docker compose -f local.yml exec -it -u 0 api alembic revision --autogenerate -m "<message>"
```

`docker compose -f local.yml exec -it -u 0 api` -> runs a command in a running container for the `api` service as root
`alembic revision --autogenerate -m "<message>"` -> generates a new migration

### Running migrations

```
docker compose -f local.yml exec -it -u 0 api alembic upgrade head
```

### Connect to DB

```
docker compose -f local.yml exec -it -u 0 postgres psql -U pranto -d ledgr
```

## Utilities

### Generate secret keys

```
python -c "import secrets; print(secrets.token_urlsafe(38))"
```
