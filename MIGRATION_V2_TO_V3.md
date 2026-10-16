# Migração CutFlow V2 -> V3

A V3 deve ser testada em uma pasta separada. Não sobrescreva a V2 antes de aprovar o novo pipeline.

## 1. Pare a V2

```bash
cd "/mnt/d/Users/Samuel/Downloads/cutflow-studio-v2"
docker compose down
```

## 2. Extraia a V3

Extraia `cutflow-studio-v3.0.0.zip` para:

```text
D:\Users\Samuel\Downloads\cutflow-studio-v3
```

## 3. Entre pelo WSL

```bash
cd "/mnt/d/Users/Samuel/Downloads/cutflow-studio-v3"
```

## 4. Suba a V3

```bash
docker compose up --build
```

## 5. Abra

```text
http://localhost:8000
```

## 6. Não copie o banco da V2 inicialmente

Para homologar corretamente a nova lógica, comece com o `data/` limpo da V3. Depois da aprovação, a migração de histórico pode ser tratada separadamente.
