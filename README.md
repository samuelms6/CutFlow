# CutFlow Studio V3.0.0

CutFlow Studio transforma vídeos longos em cortes verticais para TikTok, Instagram Reels e YouTube Shorts.

A V3 corrige o principal problema da V2: **um vídeo sem transcrição não é mais cortado por distribuição temporal**. Todo vídeo recebe primeiro uma análise audiovisual; a transcrição é opcional e acrescenta contexto semântico quando ativada.

## O que mudou na V3

### 1. Dois modos reais de análise

**Audiovisual (transcrição desativada)**
- mudanças de cena;
- movimento entre quadros;
- energia do áudio/música;
- picos de atividade;
- vales de áudio e transições usados como limites naturais;
- quantidade de cortes calculada automaticamente pela duração + qualidade.

Indicado para:
- futebol e esportes;
- videoclipes;
- montagens;
- highlights;
- vídeos predominantemente musicais.

**Híbrido (transcrição ativada)**
- todos os sinais audiovisuais acima;
- legendas existentes ou Whisper;
- gancho da fala;
- ritmo de fala;
- completude semântica;
- fechamento em final de frase;
- seleção final combina semântica + intensidade audiovisual.

Indicado para:
- podcasts;
- entrevistas;
- aulas;
- vídeos explicativos;
- conteúdo falado.

### 2. Quantidade automática

Não há mais campo "3 / 5 / 10 cortes".

O sistema calcula um orçamento máximo pela duração do vídeo e devolve somente os melhores candidatos acima do limite de qualidade. Assim, um vídeo longo pode gerar vários cortes e um vídeo curto pode gerar apenas um.

### 3. Fechamento natural

Sem transcrição, início e fim são ajustados para mudanças de cena ou vales de energia sonora próximos ao ponto ideal.

Com transcrição, o sistema também procura finais de frase e ideias completas.

### 4. Card profissional de cada corte

Cada corte mostra:
- score;
- título;
- gancho;
- modo de análise;
- motivo da seleção;
- duração;
- indicação de fechamento natural;
- breakdown do score;
- descrição;
- hashtags;
- preset e enquadramento;
- botão Editar;
- download do MP4.

### 5. Transcrição opcional

O formulário possui a opção **Transcrever fala e gerar legendas**.

Desativada:
- Whisper não é executado;
- nenhuma legenda é aplicada;
- o pipeline segue normalmente usando análise audiovisual.

Ativada:
- tenta usar legendas existentes;
- se não houver, usa faster-whisper;
- timestamps por palavra alimentam legendas Viral / Clean / Karaokê.

### 6. Tracking e enquadramento

O modo automático tenta detectar rosto e, na ausência dele, pessoa. Se a confiança não for suficiente, usa um enquadramento seguro com vídeo completo + fundo adaptado.

### 7. Áudio

O render final aplica:
- high-pass;
- low-pass;
- redução leve de ruído;
- loudness normalization;
- AAC 48 kHz.

### 8. Presets

- TikTok 1080x1920
- Instagram Reels 1080x1920
- YouTube Shorts 1080x1920

Cada preset possui bitrate e safe-area próprios.

### 9. Editor

Cada corte pode ser rerenderizado individualmente alterando:
- início;
- fim;
- título;
- preset;
- estilo de legenda;
- enquadramento;
- descrição;
- hashtags.

Se o projeto foi criado sem transcrição, o editor mantém legenda como **Sem legenda**.

### 10. Arquitetura

- FastAPI: API e interface
- Redis: broker
- Celery: worker de vídeo
- SQLite: estado local de homologação
- FFmpeg: render e áudio
- OpenCV: análise visual + tracking
- faster-whisper: transcrição opcional
- yt-dlp: ingestão autorizada de YouTube

## Rodar no WSL com Docker Engine

Entre na pasta V3:

```bash
cd "/mnt/d/Users/Samuel/Downloads/cutflow-studio-v3"
```

Pare versões antigas se estiverem usando a porta 8000:

```bash
cd "/mnt/d/Users/Samuel/Downloads/cutflow-studio-v2"
docker compose down
```

Volte para V3 e suba:

```bash
cd "/mnt/d/Users/Samuel/Downloads/cutflow-studio-v3"
docker compose up --build
```

Abra:

```text
http://localhost:8000
```

Os serviços esperados são:

```text
api
redis
worker
```

## Primeiro teste recomendado

Para um vídeo como highlights do Messi:

- Upload de arquivo
- **Transcrever fala e gerar legendas: DESATIVADO**
- Duração mínima: 20 s
- Duração máxima: 60 s
- Preset: TikTok
- Enquadramento: Automático ou Vídeo completo + fundo

Para podcast/entrevista:

- Transcrição: ATIVADA
- Legenda: Karaokê ou Viral
- Enquadramento: Automático

## OpenAI opcional

O sistema funciona sem `OPENAI_API_KEY`.

Se `OPENAI_API_KEY` e `OPENAI_MODEL` forem configurados, o modelo pode refinar título, gancho, score, motivo, descrição e hashtags dos candidatos já escolhidos localmente.

A seleção básica e o mapa audiovisual não dependem de API paga.

## YouTube

Use somente conteúdo que você possui ou tem autorização para processar.

A integração via yt-dlp possui tratamento para:
- vídeos privados;
- pedido de login/cookies;
- indisponibilidade regional;
- timeout;
- playlist acidental.

Se o YouTube bloquear a obtenção do vídeo, use upload do MP4 autorizado.

## Dados

Durante homologação, os arquivos ficam em:

```text
data/jobs/<job-id>/
```

O mapa audiovisual é salvo em:

```text
audiovisual-map.json
```

A transcrição, quando habilitada, fica em:

```text
transcript.json
```

## Estado desta entrega

A V3 é uma versão de homologação funcional. Antes de SaaS público ainda são recomendados autenticação, PostgreSQL, storage externo, quotas, billing e observabilidade centralizada.
