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
