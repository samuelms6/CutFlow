# CutFlow Studio V3.0.0 - Relatório de testes

Data: 2026-10-16

## Testes concluídos neste ambiente

- Python compileall: PASS
- Pytest: 5/5 PASS
- JavaScript syntax (`node --check`): PASS
- Probe FFmpeg: PASS
- Análise audiovisual de vídeo sintético: PASS
- Detecção de transição visual: PASS
- Quantidade automática por duração: PASS
- Seleção sem transcrição: PASS
- Seleção híbrida com segmentos de fala: PASS
- Geração de score e breakdown: PASS
- Geração local de título/gancho/descrição/hashtags sem transcrição: PASS
- Render MP4 sem legenda: PASS
- Preset TikTok 1080x1920: PASS
- Normalização/processamento de áudio no render: PASS
- Fechamento visual marcado como natural em teste sintético: PASS

## Smoke test sem transcrição

Entrada: vídeo sintético com três blocos visuais distintos + áudio contínuo.

Resultado:
- modo: audiovisual;
- transcrição: não utilizada;
- corte selecionado por atividade/transição;
- score: gerado;
- motivo: gerado;
- fechamento natural: detectado;
- MP4 final: gerado;
- resolução: 1080x1920.

## Limitação do ambiente de geração

Este ambiente não possui Docker Engine e também não possui acesso externo para instalar Celery/Redis via pip. Por isso o fluxo completo `FastAPI -> Redis -> Celery worker` não foi executado aqui.

A V2 já confirmou que a arquitetura Docker/Redis/worker funciona no WSL do usuário. A V3 precisa passar novamente por essa homologação no WSL após `docker compose up --build`.

## Validação recomendada no WSL

1. `docker compose ps` deve mostrar `api`, `redis`, `worker` como ativos.
2. Testar vídeo de highlights com transcrição desligada.
3. Confirmar `Transcrição: Desativada` e `Análise: Audiovisual`.
4. Verificar quantidade automática.
5. Verificar se cortes não têm duração idêntica por divisão mecânica.
6. Testar vídeo falado com transcrição ligada.
7. Abrir Editor e rerenderizar um corte.
8. Testar TikTok/Reels/Shorts.
