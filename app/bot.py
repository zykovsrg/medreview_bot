from __future__ import annotations

import html
import logging
from datetime import datetime, timezone

from aiogram import F, Router
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message

from app.google_clients import GoogleRepository
from app.keyboards import (
    completed_review_keyboard,
    doctor_choice_keyboard,
    finish_status_keyboard,
    illustrations_keyboard,
    main_menu_keyboard,
    outline_keyboard,
    reminder_options_keyboard,
    review_keyboard,
    tasks_keyboard,
)
from app.reminders import ReminderService
from app.models import CommentRecord, StoredDoctor, normalize_surname
from app.storage import Storage


logger = logging.getLogger(__name__)


class BotStates(StatesGroup):
    waiting_surname = State()
    waiting_comment = State()
    viewing_section = State()
    viewing_illustrations = State()


def split_long_text(text: str, limit: int = 3500) -> list[str]:
    if len(text) <= limit:
        return [text]

    chunks: list[str] = []
    current = ""
    for paragraph in text.split("\n\n"):
        candidate = paragraph if not current else f"{current}\n\n{paragraph}"
        if len(candidate) <= limit:
            current = candidate
            continue
        if current:
            chunks.append(current)
            current = paragraph
            continue
        for index in range(0, len(paragraph), limit):
            chunks.append(paragraph[index : index + limit])
        current = ""
    if current:
        chunks.append(current)
    return chunks


def create_router(repository: GoogleRepository, storage: Storage, settings, reminders: ReminderService) -> Router:
    router = Router()
    memo_text = (
        "Как проверить текст\n\n"
        "<b>1. Проверяем только факты, но не стиль</b>\n"
        "Стиль сильно упрощён под пациентские запросы в поисковиках, это важно для продвижения.\n\n"
        "<b>2. Прочитать текст и оставить комментарии</b>\n"
        "Текст переписывать не нужно. Чтобы оставить комментарий к разделу, просто отправьте сообщение. "
        "Можно выделить часть текста и отвечать реплаем: так комментарий уйдет с нужным куском текста. "
        "Можно записать голосовое сообщение\n\n"
        "<b>3. Проверить продуктовый блок</b>\n"
        "В документе он выделен рамкой. В нём указаны сильные стороны нашей клиники: если есть, что добавить — это очень нам поможет. "
        "Например, информацию про оборудование, процедуры, которые выгодно выделяют нас на фоне других клиник.\n\n"
        "<b>Если нет времени читать или много замечаний</b>\n"
        "Свяжитесь с редактором:\n"
        "Телеграм: @zykovsrg;\n"
        "Макс и другие мессенджеры: +7 922 990-48-00;\n"
        "почта: s.zykov@hadassah.moscow.\n"
        "Договоримся о встрече и вместе пройдёмся по тексту."
    )

    async def send_google_error(target: Message | CallbackQuery) -> None:
        text = (
            "Не удалось получить данные из Google. "
            "Скорее всего, не совпал секрет между ботом и Apps Script."
        )
        sender = target.message.answer if isinstance(target, CallbackQuery) else target.answer
        await sender(text, reply_markup=main_menu_keyboard())

    async def send_document_link(target: Message | CallbackQuery, document_url: str, intro_text: str | None = None) -> None:
        sender = target.message.answer if isinstance(target, CallbackQuery) else target.answer
        lines = []
        if intro_text:
            lines.append(intro_text)
            lines.append("")
        lines.append("Ссылка на документ:")
        lines.append(document_url)
        await sender("\n".join(lines))

    async def forward_voice_comment(
        message: Message,
        section_title_override: str | None = None,
    ) -> str:
        doctor = storage.get_doctor(message.from_user.id)
        session = storage.get_session(message.from_user.id)
        if doctor is None or session is None:
            await message.answer("Сначала выберите врача и статью.")
            return "missing_context"

        task = repository.get_task_by_row(doctor.doctor_name, session.sheet_row_number)
        if task is None:
            await message.answer("Не удалось найти актуальную статью. Обновите список и выберите её заново.")
            return "missing_task"

        if section_title_override is None:
            document = repository.get_document(session.document_url)
            current_index = max(0, min(session.current_section_index, len(document.sections) - 1))
            section_title = document.sections[current_index].title
        else:
            section_title = section_title_override

        report_chat = storage.get_report_chat()
        if report_chat is None:
            await message.answer(
                "Голосовой комментарий пока некуда переслать. "
                f"Нужно сначала зарегистрировать чат {settings.report_recipient_label} через /register_report_chat."
            )
            return "missing_report_chat"

        context_text = (
            "Голосовой комментарий от врача\n"
            f"Врач: {doctor.doctor_name}\n"
            f"Тема: {task.topic or session.article_title}\n"
            f"Раздел: {section_title}\n"
            f"Документ: {session.document_url}"
        )

        try:
            await message.bot.send_message(report_chat.chat_id, context_text)
            await message.bot.copy_message(report_chat.chat_id, message.chat.id, message.message_id)
        except Exception:
            logger.exception("Failed to forward voice comment")
            await message.answer("Не удалось переслать голосовой комментарий редактору. Попробуйте ещё раз чуть позже.")
            return "forward_failed"

        await message.answer("Голосовой комментарий отправлен редактору.")
        return "ok"

    def format_report_text(
        doctor_name: str,
        task_topic: str,
        document_title: str,
        document_url: str,
        final_status: str,
        comments: list,
    ) -> str:
        text_lines = [
            "Итог проверки статьи",
            f"Врач: {doctor_name}",
            f"Тема: {task_topic}",
            f"Документ: {document_title}",
            f"Статус: {final_status}",
            f"Комментарии: {len(comments)}",
            f"Ссылка: {document_url}",
        ]

        if comments:
            text_lines.append("")
            text_lines.append("Замечания:")
            for index, row in enumerate(comments, start=1):
                line = f"{index}. {row['section_title']}"
                if row["quote_text"]:
                    line += f"\nЦитата: {row['quote_text']}"
                line += f"\nКомментарий: {row['comment_text']}"
                text_lines.append(line)
        else:
            text_lines.append("")
            text_lines.append("Замечаний не добавлено.")

        return "\n".join(text_lines)

    async def send_report_to_registered_chat(source_message: Message, report_text: str) -> str:
        report_chat = storage.get_report_chat()
        if report_chat is None:
            return (
                "Отчёт не отправлен: чат для отчётов ещё не зарегистрирован. "
                f"Откройте бота из аккаунта {settings.report_recipient_label} и отправьте команду /register_report_chat."
            )

        try:
            await source_message.bot.send_message(report_chat.chat_id, report_text)
            return f"Итоговый отчёт отправлен в {report_chat.label or settings.report_recipient_label}."
        except Exception:
            logger.exception("Failed to send report message")
            return "Статус обновлён, но отчёт отправить не удалось."

    async def send_dashboard(target: Message | CallbackQuery, doctor: StoredDoctor, state: FSMContext) -> None:
        try:
            tasks = repository.get_tasks_for_doctor(doctor.doctor_name)
        except Exception:
            logger.exception("Failed to load doctor tasks")
            await send_google_error(target)
            return
        text_lines = [
            f"Врач: {doctor.doctor_name}",
            f"Сейчас на проверке: {len(tasks)}",
        ]

        if tasks:
            text_lines.append("")
            text_lines.append("Выберите статью из списка ниже.")
        else:
            text_lines.append("")
            text_lines.append(
                f"Сейчас нет статей со статусом «{settings.pending_status_value}». Можно позже нажать «Список статей» и обновить данные."
            )

        sender = target.message.answer if isinstance(target, CallbackQuery) else target.answer
        await sender(
            "\n".join(text_lines),
            reply_markup=tasks_keyboard(tasks) if tasks else main_menu_keyboard(),
        )
        await state.clear()

    async def send_outline(
        target: Message | CallbackQuery,
        doctor: StoredDoctor,
        row_number: int,
        state: FSMContext,
    ) -> None:
        task = repository.get_task_by_row(doctor.doctor_name, row_number)
        if task is None:
            sender = target.message.answer if isinstance(target, CallbackQuery) else target.answer
            await sender("Не нашёл эту статью в актуальном списке. Нажмите «Список статей», чтобы обновить данные.")
            return

        document = repository.get_document(task.document_url)
        storage.save_session(
            telegram_user_id=doctor.telegram_user_id,
            sheet_row_number=task.row_number,
            article_id=task.article_id,
            article_title=document.title,
            document_url=task.document_url,
            current_section_index=0,
        )

        outline = "\n".join(f"{section.index}. {section.title}" for section in document.sections)
        text = (
            f"Тема: {task.topic}\n"
            "\n"
            f"Структура:\n{outline}"
        )

        sender = target.message.answer if isinstance(target, CallbackQuery) else target.answer
        await sender(text, reply_markup=outline_keyboard(task.row_number))
        await state.clear()

    async def send_section(
        target: Message | CallbackQuery,
        doctor: StoredDoctor,
        row_number: int,
        section_index: int,
        state: FSMContext,
    ) -> None:
        task = repository.get_task_by_row(doctor.doctor_name, row_number)
        if task is None:
            sender = target.message.answer if isinstance(target, CallbackQuery) else target.answer
            await sender("Статья больше не найдена в списке. Обновите список статей.")
            return

        document = repository.get_document(task.document_url)
        if not document.sections:
            sender = target.message.answer if isinstance(target, CallbackQuery) else target.answer
            await sender("В документе не удалось выделить разделы H2.")
            return

        section_index = max(0, min(section_index, len(document.sections) - 1))
        section = document.sections[section_index]
        storage.update_session_section(doctor.telegram_user_id, section_index)
        await state.set_state(BotStates.viewing_section)
        await state.update_data(comment_context="section", active_row_number=row_number)

        intro_block = ""
        if section_index == 0 and document.intro:
            intro_block = f"{html.escape(document.intro[:700])}\n\n"

        header = f"Раздел {section.index}/{len(document.sections)}\n\n"
        title = f"<b>{html.escape(section.title)}</b>\n\n"
        body = html.escape(section.body or "В этом разделе пока нет текста.")
        chunks = split_long_text(f"{header}{intro_block}{title}{body}")
        sender = target.message.answer if isinstance(target, CallbackQuery) else target.answer

        for chunk_index, chunk in enumerate(chunks):
            reply_markup = (
                review_keyboard(
                    row_number,
                    section_index,
                    len(document.sections),
                    show_illustrations=(section_index == len(document.sections) - 1),
                )
                if chunk_index == len(chunks) - 1
                else None
            )
            await sender(chunk, reply_markup=reply_markup, parse_mode="HTML")

    async def persist_comment(
        message: Message,
        state: FSMContext,
        comment_text: str,
        section_title_override: str | None = None,
        section_index_override: int | None = None,
    ) -> None:
        doctor = storage.get_doctor(message.from_user.id)
        session = storage.get_session(message.from_user.id)
        if doctor is None or session is None:
            await message.answer("Сначала выберите врача и статью.")
            return

        task = repository.get_task_by_row(doctor.doctor_name, session.sheet_row_number)
        if task is None:
            await message.answer("Не удалось найти актуальную статью. Обновите список и выберите её заново.")
            return

        if section_title_override is None or section_index_override is None:
            document = repository.get_document(session.document_url)
            current_index = max(0, min(session.current_section_index, len(document.sections) - 1))
            section = document.sections[current_index]
            section_index = section.index
            section_title = section.title
        else:
            section_index = section_index_override
            section_title = section_title_override
        quote_text = message.quote.text.strip() if message.quote and message.quote.text else None

        record = CommentRecord(
            telegram_user_id=message.from_user.id,
            doctor_name=doctor.doctor_name,
            sheet_row_number=session.sheet_row_number,
            article_id=session.article_id,
            article_title=session.article_title,
            document_url=session.document_url,
            section_index=section_index,
            section_title=section_title,
            review_started_at=session.review_started_at,
            quote_text=quote_text,
            comment_text=comment_text.strip(),
            created_at=datetime.now(timezone.utc).isoformat(),
        )
        storage.add_comment(record)

        try:
            repository.append_comment(record)
        except Exception:
            logger.exception("Failed to append comment to Google Sheets")

        if quote_text:
            await message.answer("Комментарий с цитатой сохранён.")
        else:
            await message.answer("Комментарий сохранён.")
        state_data = await state.get_data()
        if state_data.get("comment_context") == "illustrations":
            await state.set_state(BotStates.viewing_illustrations)
        else:
            await state.set_state(BotStates.viewing_section)

    @router.message(CommandStart())
    async def handle_start(message: Message, state: FSMContext) -> None:
        doctor = storage.get_doctor(message.from_user.id)
        if doctor is not None:
            await message.answer(
                "Вы уже ввели фамилию. Ниже можно посмотреть список статей или сменить аккаунт.",
                reply_markup=main_menu_keyboard(),
            )
            await send_dashboard(message, doctor, state)
            return

        await state.set_state(BotStates.waiting_surname)
        await message.answer(
            "Здравствуйте! Этот бот помогает проверить публикации для сайта нашей клиники. "
            "Если бот плохо или неудобно работает, напишите @zykovsrg.\n\n"
            "Введите Вашу фамилию:",
            reply_markup=main_menu_keyboard(),
        )

    @router.message(Command("register_report_chat"))
    async def handle_register_report_chat(message: Message) -> None:
        label = f"@{message.from_user.username}" if message.from_user.username else (message.from_user.full_name or str(message.chat.id))
        storage.set_report_chat(message.chat.id, label)
        await message.answer(f"Этот чат зарегистрирован для итоговых отчётов. Сейчас отчёты будут уходить сюда: {label}")

    @router.message(F.text == "Сменить аккаунт")
    async def handle_change_doctor(message: Message, state: FSMContext) -> None:
        storage.clear_doctor(message.from_user.id)
        await state.set_state(BotStates.waiting_surname)
        await message.answer("Введите фамилию врача заново.")

    @router.message(F.text == "Список статей")
    async def handle_tasks_list(message: Message, state: FSMContext) -> None:
        doctor = storage.get_doctor(message.from_user.id)
        if doctor is None:
            await state.set_state(BotStates.waiting_surname)
            await message.answer("Сначала введите фамилию врача.")
            return
        await send_dashboard(message, doctor, state)

    @router.message(F.text == "Мои комментарии")
    async def handle_my_comments(message: Message, state: FSMContext) -> None:
        await state.clear()
        summary_rows = storage.get_comment_summary(message.from_user.id)
        recent_rows = storage.get_recent_comments(message.from_user.id, limit=5)

        if not summary_rows:
            await message.answer("Пока нет сохранённых комментариев.")
            return

        text_lines = ["Сводка по вашим комментариям:"]
        for row in summary_rows[:10]:
            text_lines.append(f"• {row['article_title']}: {row['comments_count']}")

        if recent_rows:
            text_lines.append("")
            text_lines.append("Последние комментарии:")
            for row in recent_rows:
                preview = row["comment_text"].strip().replace("\n", " ")
                if len(preview) > 80:
                    preview = f"{preview[:77]}..."
                if row["quote_text"]:
                    quote_preview = row["quote_text"].strip().replace("\n", " ")
                    if len(quote_preview) > 50:
                        quote_preview = f"{quote_preview[:47]}..."
                    text_lines.append(f"• {row['section_title']} | «{quote_preview}»: {preview}")
                else:
                    text_lines.append(f"• {row['section_title']}: {preview}")

        await message.answer("\n".join(text_lines))

    @router.message(BotStates.waiting_surname)
    async def handle_surname(message: Message, state: FSMContext) -> None:
        surname = normalize_surname(message.text or "")
        if not surname:
            await message.answer("Не понял фамилию. Напишите её ещё раз одним сообщением.")
            return

        try:
            doctor_choices = repository.get_doctor_choices(surname)
        except Exception:
            logger.exception("Failed to load doctor choices")
            await send_google_error(message)
            return
        if not doctor_choices:
            await message.answer(
                f"По этой фамилии не нашёл статей со статусом «{settings.pending_status_value}». Проверьте написание или попробуйте позже."
            )
            return

        if len(doctor_choices) == 1:
            doctor_name = doctor_choices[0]
            storage.upsert_doctor(message.from_user.id, surname, doctor_name)
            await state.clear()
            await message.answer(
                f"Привязал вас к врачу: {doctor_name}",
                reply_markup=main_menu_keyboard(),
            )
            doctor = storage.get_doctor(message.from_user.id)
            assert doctor is not None
            await send_dashboard(message, doctor, state)
            return

        await state.update_data(doctor_choices=doctor_choices, surname=surname)
        await message.answer(
            "Нашёл несколько врачей. Выберите нужного.",
            reply_markup=doctor_choice_keyboard(doctor_choices),
        )

    @router.callback_query(F.data.startswith("doctor:"))
    async def handle_doctor_choice(callback: CallbackQuery, state: FSMContext) -> None:
        data = await state.get_data()
        doctor_choices: list[str] = data.get("doctor_choices", [])
        surname = data.get("surname", "")
        index = int(callback.data.split(":", maxsplit=1)[1])

        if index >= len(doctor_choices):
            await callback.answer("Вариант устарел. Введите фамилию заново.", show_alert=True)
            await state.set_state(BotStates.waiting_surname)
            return

        doctor_name = doctor_choices[index]
        storage.upsert_doctor(callback.from_user.id, surname, doctor_name)
        await state.clear()
        await callback.answer()
        await callback.message.answer(
            f"Привязал вас к врачу: {doctor_name}",
            reply_markup=main_menu_keyboard(),
        )
        doctor = storage.get_doctor(callback.from_user.id)
        assert doctor is not None
        await send_dashboard(callback, doctor, state)

    @router.callback_query(F.data == "dashboard")
    async def handle_dashboard_callback(callback: CallbackQuery, state: FSMContext) -> None:
        doctor = storage.get_doctor(callback.from_user.id)
        if doctor is None:
            await callback.answer("Сначала введите фамилию.", show_alert=True)
            await state.set_state(BotStates.waiting_surname)
            return
        await callback.answer()
        await send_dashboard(callback, doctor, state)

    @router.callback_query(F.data.startswith("article:"))
    async def handle_article_choice(callback: CallbackQuery, state: FSMContext) -> None:
        doctor = storage.get_doctor(callback.from_user.id)
        if doctor is None:
            await callback.answer("Сначала введите фамилию врача.", show_alert=True)
            await state.set_state(BotStates.waiting_surname)
            return
        row_number = int(callback.data.split(":", maxsplit=1)[1])
        await callback.answer()
        await send_outline(callback, doctor, row_number, state)

    @router.callback_query(F.data.startswith("outline:"))
    async def handle_outline_callback(callback: CallbackQuery, state: FSMContext) -> None:
        doctor = storage.get_doctor(callback.from_user.id)
        if doctor is None:
            await callback.answer("Сначала введите фамилию врача.", show_alert=True)
            return
        row_number = int(callback.data.split(":", maxsplit=1)[1])
        await callback.answer()
        await send_outline(callback, doctor, row_number, state)

    @router.callback_query(F.data.startswith("start:"))
    async def handle_start_review(callback: CallbackQuery, state: FSMContext) -> None:
        doctor = storage.get_doctor(callback.from_user.id)
        if doctor is None:
            await callback.answer("Сначала введите фамилию врача.", show_alert=True)
            return
        row_number = int(callback.data.split(":", maxsplit=1)[1])
        await callback.answer()
        await send_section(callback, doctor, row_number, section_index=0, state=state)

    @router.callback_query(F.data.startswith("nav:"))
    async def handle_navigation(callback: CallbackQuery, state: FSMContext) -> None:
        doctor = storage.get_doctor(callback.from_user.id)
        if doctor is None:
            await callback.answer("Сначала введите фамилию врача.", show_alert=True)
            return
        _, row_number, section_index = callback.data.split(":")
        await callback.answer()
        await send_section(callback, doctor, int(row_number), int(section_index), state)

    @router.callback_query(F.data.startswith("doclink:"))
    async def handle_document_link(callback: CallbackQuery, state: FSMContext) -> None:
        doctor = storage.get_doctor(callback.from_user.id)
        if doctor is None:
            await callback.answer("Сначала введите фамилию врача.", show_alert=True)
            return
        row_number = int(callback.data.split(":", maxsplit=1)[1])
        task = repository.get_task_by_row(doctor.doctor_name, row_number)
        if task is None:
            await callback.answer("Не нашёл эту статью в актуальном списке.", show_alert=True)
            return
        await callback.answer()
        await send_document_link(callback, task.document_url)

    @router.callback_query(F.data.startswith("memo:"))
    async def handle_review_memo(callback: CallbackQuery) -> None:
        await callback.answer()
        await callback.message.answer(memo_text, parse_mode="HTML")

    @router.callback_query(F.data == "remind_menu")
    async def handle_remind_menu(callback: CallbackQuery) -> None:
        doctor = storage.get_doctor(callback.from_user.id)
        if doctor is None:
            await callback.answer("Сначала введите фамилию врача.", show_alert=True)
            return
        await callback.answer()
        await callback.message.answer(
            "Когда напомнить?",
            reply_markup=reminder_options_keyboard(),
        )

    @router.callback_query(F.data.startswith("remind_set:"))
    async def handle_remind_set(callback: CallbackQuery) -> None:
        doctor = storage.get_doctor(callback.from_user.id)
        if doctor is None:
            await callback.answer("Сначала введите фамилию врача.", show_alert=True)
            return

        option = callback.data.split(":", maxsplit=1)[1]
        label = reminders.describe_option(option)
        due_at = reminders.calculate_due_at(option)
        reminders.schedule_for_doctor(
            telegram_user_id=callback.from_user.id,
            doctor_name=doctor.doctor_name,
            due_at=due_at,
            label=label,
        )
        await callback.answer()
        await callback.message.answer(f"Хорошо, напомню {label}.")

    @router.callback_query(F.data.startswith("illustrations:"))
    async def handle_illustrations(callback: CallbackQuery, state: FSMContext) -> None:
        doctor = storage.get_doctor(callback.from_user.id)
        session = storage.get_session(callback.from_user.id)
        if doctor is None or session is None:
            await callback.answer("Сначала выберите статью.", show_alert=True)
            return
        row_number = int(callback.data.split(":", maxsplit=1)[1])
        task = repository.get_task_by_row(doctor.doctor_name, row_number)
        if task is None:
            await callback.answer("Не нашёл эту статью в актуальном списке.", show_alert=True)
            return

        await state.set_state(BotStates.viewing_illustrations)
        await state.update_data(comment_context="illustrations", active_row_number=row_number)
        await callback.answer()
        await send_document_link(
            callback,
            task.document_url,
            intro_text=(
                "Откройте документ, проверьте иллюстрации и пришлите замечания сюда сообщением. "
                "Я сохраню их как комментарии к иллюстрациям."
            ),
        )
        await callback.message.answer(
            "После проверки иллюстраций можно оставить комментарии сюда или завершить статью.",
            reply_markup=illustrations_keyboard(row_number),
        )

    @router.callback_query(F.data == "finish")
    async def handle_finish(callback: CallbackQuery, state: FSMContext) -> None:
        await callback.answer()
        await callback.message.answer(
            "Выберите итог проверки:",
            reply_markup=finish_status_keyboard(),
        )

    @router.callback_query(F.data.startswith("finish_status:"))
    async def handle_finish_status(callback: CallbackQuery, state: FSMContext) -> None:
        doctor = storage.get_doctor(callback.from_user.id)
        session = storage.get_session(callback.from_user.id)
        if doctor is None or session is None:
            await callback.answer("Сессия статьи уже завершена.", show_alert=True)
            return

        selected_action = callback.data.split(":", maxsplit=1)[1]
        final_status = (
            settings.approved_status_value
            if selected_action == "Проверено"
            else settings.pending_status_value
        )
        task = repository.get_task_by_row(doctor.doctor_name, session.sheet_row_number)
        topic = task.topic if task is not None else session.article_title

        try:
            repository.update_article_status(session.sheet_row_number, final_status)
        except Exception:
            logger.exception("Failed to update article status")
            await callback.answer()
            await callback.message.answer(
                "Не удалось обновить статус в таблице. Попробуйте ещё раз чуть позже.",
                reply_markup=main_menu_keyboard(),
            )
            return

        comments = storage.get_comments_for_review(
            callback.from_user.id,
            session.sheet_row_number,
            session.review_started_at,
        )
        report_text = format_report_text(
            doctor_name=doctor.doctor_name,
            task_topic=topic,
            document_title=session.article_title,
            document_url=session.document_url,
            final_status=final_status,
            comments=comments,
        )
        review_id = storage.create_completed_review(
            telegram_user_id=callback.from_user.id,
            doctor_name=doctor.doctor_name,
            sheet_row_number=session.sheet_row_number,
            article_id=session.article_id,
            article_title=session.article_title,
            document_url=session.document_url,
            task_topic=topic,
            review_started_at=session.review_started_at,
            final_status=final_status,
        )
        report_result = await send_report_to_registered_chat(callback.message, report_text)

        storage.clear_session(callback.from_user.id)
        await state.clear()
        await callback.answer()
        await callback.message.answer(
            f"Статус статьи обновлён: {final_status}.\n{report_result}",
            reply_markup=completed_review_keyboard(
                review_id,
                is_approved=(final_status == settings.approved_status_value),
            ),
        )
        if doctor is not None:
            await send_dashboard(callback, doctor, state)

    @router.callback_query(F.data.startswith("review_status:"))
    async def handle_review_status_change(callback: CallbackQuery, state: FSMContext) -> None:
        doctor = storage.get_doctor(callback.from_user.id)
        if doctor is None:
            await callback.answer("Сначала выберите врача.", show_alert=True)
            return

        _, review_id_raw, action = callback.data.split(":", maxsplit=2)
        review = storage.get_completed_review(int(review_id_raw))
        if review is None or review.telegram_user_id != callback.from_user.id:
            await callback.answer("Не нашёл эту завершённую проверку.", show_alert=True)
            return

        new_status = (
            settings.approved_status_value
            if action == "approved"
            else settings.pending_status_value
        )

        try:
            repository.update_article_status(review.sheet_row_number, new_status)
        except Exception:
            logger.exception("Failed to rewrite article status")
            await callback.answer("Не удалось переписать статус.", show_alert=True)
            return

        storage.update_completed_review_status(review.id, new_status)
        comments = storage.get_comments_for_review(
            review.telegram_user_id,
            review.sheet_row_number,
            review.review_started_at,
        )
        report_text = format_report_text(
            doctor_name=review.doctor_name,
            task_topic=review.task_topic,
            document_title=review.article_title,
            document_url=review.document_url,
            final_status=new_status,
            comments=comments,
        )
        report_result = await send_report_to_registered_chat(callback.message, report_text)

        await callback.answer("Статус обновлён.")
        await callback.message.answer(
            f"Статус статьи переписан: {new_status}.\n{report_result}",
            reply_markup=completed_review_keyboard(
                review.id,
                is_approved=(new_status == settings.approved_status_value),
            ),
        )

    @router.message(BotStates.waiting_comment)
    async def handle_explicit_comment(message: Message, state: FSMContext) -> None:
        if not (message.text and message.text.strip()):
            await message.answer("Комментарий пустой. Напишите текст одним сообщением.")
            return
        await persist_comment(message, state, message.text)

    @router.message(BotStates.viewing_section, F.voice)
    async def handle_voice_section_comment(message: Message, state: FSMContext) -> None:
        result = await forward_voice_comment(message)
        if result == "ok":
            await state.set_state(BotStates.viewing_section)

    @router.message(BotStates.viewing_section)
    async def handle_inline_comment(message: Message, state: FSMContext) -> None:
        text = (message.text or "").strip()
        if not text:
            await message.answer("Если хотите оставить комментарий, отправьте его текстом.")
            return
        await persist_comment(message, state, text)

    @router.message(BotStates.viewing_illustrations, F.voice)
    async def handle_voice_illustrations_comment(message: Message, state: FSMContext) -> None:
        result = await forward_voice_comment(message, section_title_override="Иллюстрации")
        if result == "ok":
            await state.set_state(BotStates.viewing_illustrations)

    @router.message(BotStates.viewing_illustrations)
    async def handle_illustrations_comment(message: Message, state: FSMContext) -> None:
        text = (message.text or "").strip()
        if not text:
            await message.answer("Если хотите оставить комментарий по иллюстрациям, отправьте его текстом.")
            return
        await persist_comment(
            message,
            state,
            text,
            section_title_override="Иллюстрации",
            section_index_override=999,
        )

    return router
