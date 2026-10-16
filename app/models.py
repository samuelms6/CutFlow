from __future__ import annotations

from pydantic import BaseModel, Field, HttpUrl, model_validator


class JobOptions(BaseModel):
    min_duration: int = Field(default=20, ge=10, le=120)
    max_duration: int = Field(default=60, ge=15, le=180)
    transcribe: bool = True
    subtitle_style: str = Field(default="viral", pattern="^(none|viral|clean|karaoke)$")
    preset: str = Field(default="tiktok", pattern="^(tiktok|reels|shorts)$")
    framing: str = Field(default="auto", pattern="^(auto|face|center|fit)$")

    @model_validator(mode="after")
    def validate_duration(self):
        if self.max_duration < self.min_duration:
            raise ValueError("max_duration deve ser maior ou igual a min_duration")
        if not self.transcribe:
            self.subtitle_style = "none"
        return self


class UrlJobRequest(JobOptions):
    url: HttpUrl
    authorization_confirmed: bool

    @model_validator(mode="after")
    def validate_auth(self):
        if not self.authorization_confirmed:
            raise ValueError("É necessário confirmar que você possui autorização para processar o conteúdo.")
        return self


class ClipEditRequest(BaseModel):
    title: str | None = Field(default=None, max_length=120)
    start: float | None = Field(default=None, ge=0)
    end: float | None = Field(default=None, gt=0)
    subtitle_style: str | None = Field(default=None, pattern="^(none|viral|clean|karaoke)$")
    preset: str | None = Field(default=None, pattern="^(tiktok|reels|shorts)$")
    framing: str | None = Field(default=None, pattern="^(auto|face|center|fit)$")
    description: str | None = Field(default=None, max_length=500)
    hashtags: list[str] | None = Field(default=None, max_length=15)

    @model_validator(mode="after")
    def validate_range(self):
        if self.start is not None and self.end is not None and self.end <= self.start:
            raise ValueError("O fim deve ser maior que o início.")
        return self
