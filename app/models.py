from __future__ import annotations

from dataclasses import dataclass


def normalize_text(value: str) -> str:
    return " ".join(value.lower().replace("ё", "е").split())


def normalize_surname(value: str) -> str:
    cleaned = normalize_text(value)
    return cleaned.split(" ", maxsplit=1)[0] if cleaned else ""


@dataclass(slots=True, frozen=True)
class ArticleTask:
    row_number: int
    article_id: str
    direction: str
    topic: str
    status: str
    author: str
    due_date: str
    document_url: str
    site_url: str
    doctor_name: str
    priority: str

    @property
    def doctor_surname(self) -> str:
        return normalize_surname(self.doctor_name)


@dataclass(slots=True, frozen=True)
class Section:
    index: int
    title: str
    body: str


@dataclass(slots=True, frozen=True)
class ArticleDocument:
    doc_id: str
    title: str
    intro: str
    document_url: str
    sections: list[Section]


@dataclass(slots=True, frozen=True)
class StoredDoctor:
    telegram_user_id: int
    surname: str
    doctor_name: str


@dataclass(slots=True, frozen=True)
class ReviewSession:
    telegram_user_id: int
    sheet_row_number: int
    article_id: str
    article_title: str
    document_url: str
    current_section_index: int
    review_started_at: str


@dataclass(slots=True, frozen=True)
class CommentRecord:
    telegram_user_id: int
    doctor_name: str
    sheet_row_number: int
    article_id: str
    article_title: str
    document_url: str
    section_index: int
    section_title: str
    review_started_at: str
    quote_text: str | None
    comment_text: str
    created_at: str


@dataclass(slots=True, frozen=True)
class ReportChat:
    chat_id: int
    label: str


@dataclass(slots=True, frozen=True)
class CompletedReview:
    id: int
    telegram_user_id: int
    doctor_name: str
    sheet_row_number: int
    article_id: str
    article_title: str
    document_url: str
    task_topic: str
    review_started_at: str
    final_status: str
    completed_at: str
