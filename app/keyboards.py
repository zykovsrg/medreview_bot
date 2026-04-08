from __future__ import annotations

from aiogram.types import InlineKeyboardMarkup, KeyboardButton, ReplyKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder

from app.models import ArticleTask


def main_menu_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="Список статей")],
            [KeyboardButton(text="Сменить аккаунт")],
        ],
        resize_keyboard=True,
    )


def doctor_choice_keyboard(doctors: list[str]) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for index, doctor_name in enumerate(doctors):
        builder.button(text=doctor_name, callback_data=f"doctor:{index}")
    builder.adjust(1)
    return builder.as_markup()


def tasks_keyboard(tasks: list[ArticleTask]) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    for task in tasks:
        builder.button(text=task.topic[:64], callback_data=f"article:{task.row_number}")
    builder.adjust(1)
    return builder.as_markup()


def outline_keyboard(row_number: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="Начать проверку", callback_data=f"start:{row_number}")
    builder.button(text="Как быстро проверить текст", callback_data=f"memo:{row_number}")
    builder.button(text="Ссылка на документ", callback_data=f"doclink:{row_number}")
    builder.button(text="К списку статей", callback_data="dashboard")
    builder.adjust(1)
    return builder.as_markup()


def finish_status_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="Не проверено", callback_data="finish_status:Не проверено")
    builder.button(text="Проверено", callback_data="finish_status:Проверено")
    builder.adjust(1)
    return builder.as_markup()


def completed_review_keyboard(review_id: int, is_approved: bool) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    if is_approved:
        builder.button(text="Не проверено", callback_data=f"review_status:{review_id}:pending")
    else:
        builder.button(text="Проверено", callback_data=f"review_status:{review_id}:approved")
    builder.button(text="К списку статей", callback_data="dashboard")
    builder.adjust(1)
    return builder.as_markup()


def illustrations_keyboard(row_number: int) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="К структуре", callback_data=f"outline:{row_number}")
    builder.button(text="Завершить статью", callback_data="finish")
    builder.adjust(1)
    return builder.as_markup()


def review_keyboard(
    row_number: int,
    section_index: int,
    sections_total: int,
    show_illustrations: bool = False,
) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    if section_index > 0:
        builder.button(text="Назад", callback_data=f"nav:{row_number}:{section_index - 1}")
    if section_index < sections_total - 1:
        builder.button(text="Далее", callback_data=f"nav:{row_number}:{section_index + 1}")
    if show_illustrations:
        builder.button(text="Проверить иллюстрации", callback_data=f"illustrations:{row_number}")
    builder.button(text="К структуре", callback_data=f"outline:{row_number}")
    builder.button(text="Завершить статью", callback_data="finish")
    if show_illustrations:
        builder.adjust(2, 1, 1, 1)
    else:
        builder.adjust(2, 1, 1)
    return builder.as_markup()
