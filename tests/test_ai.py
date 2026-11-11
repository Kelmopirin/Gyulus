import os
import unittest
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import discord

with patch.dict(os.environ, {"OPENAI_API_KEY": "test-key"}):
    from cogs.ai import AI, summary_limits, summary_suggestions


class SummaryLimitTests(unittest.TestCase):
    def test_limits_increase_with_elapsed_time(self):
        cases = [
            (timedelta(minutes=59), (600, 500)),
            (timedelta(hours=1), (1200, 900)),
            (timedelta(hours=6), (2400, 1700)),
            (timedelta(hours=12), (3800, 2600)),
            (timedelta(hours=23, minutes=59), (3800, 2600)),
        ]
        for elapsed, expected in cases:
            with self.subTest(elapsed=elapsed):
                self.assertEqual(summary_limits(elapsed), expected)


class SummaryTests(unittest.IsolatedAsyncioTestCase):
    def make_context(self, messages=()):
        async def history(**kwargs):
            channel.history_args = kwargs
            for message in messages:
                yield message

        channel = SimpleNamespace(history=history, history_args=None)
        return SimpleNamespace(
            defer=AsyncMock(),
            send=AsyncMock(),
            channel=channel,
            author=SimpleNamespace(
                name="Tester", avatar=None,
                display_avatar=SimpleNamespace(url="https://example.com/avatar.png"),
            ),
        )

    async def run_summary(self, ctx, since, end=None):
        await AI.summary.callback(AI(None), ctx, since, end)
        ctx.defer.assert_awaited_once()

    async def test_invalid_time(self):
        ctx = self.make_context()
        await self.run_summary(ctx, "not-a-time")
        self.assertIn("Hibás időpont", ctx.send.await_args.args[0])

    async def test_out_of_range_time(self):
        ctx = self.make_context()
        await self.run_summary(ctx, "99:00")
        self.assertIn("Hibás időpont", ctx.send.await_args.args[0])

    async def test_empty_history(self):
        ctx = self.make_context()
        await self.run_summary(ctx, "17:05")
        self.assertIn("Nem találtam üzenetet", ctx.send.await_args.args[0])

    async def test_success_without_custom_avatar(self):
        message = SimpleNamespace(
            author=SimpleNamespace(bot=False, name="User"),
            created_at=datetime.now(timezone.utc),
            content="Hello",
        )
        ctx = self.make_context([message])
        response = SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content="Összefoglaló"), finish_reason="stop")]
        )
        with patch("cogs.ai.datetime", wraps=datetime) as clock:
            clock.now.return_value = datetime(2026, 11, 11, 17, 35)
            with patch("cogs.ai.client.chat.completions.create", return_value=response) as create:
                await self.run_summary(ctx, "17:05")
        self.assertEqual(create.call_args.kwargs["model"], "gpt-6-luna")
        self.assertEqual(create.call_args.kwargs["reasoning_effort"], "none")
        self.assertEqual(create.call_args.kwargs["max_completion_tokens"], 500)
        self.assertIn("600 karakter", create.call_args.kwargs["messages"][0]["content"])
        self.assertIn("0.5 óra", create.call_args.kwargs["messages"][1]["content"])
        embed = ctx.send.await_args.kwargs["embed"]
        self.assertEqual(embed.description, "Összefoglaló")
        self.assertEqual(embed.author.icon_url, "https://example.com/avatar.png")

    async def test_api_error(self):
        message = SimpleNamespace(
            author=SimpleNamespace(bot=False, name="User"),
            created_at=datetime.now(timezone.utc),
            content="Hello",
        )
        ctx = self.make_context([message])
        with patch("cogs.ai.client.chat.completions.create", side_effect=RuntimeError("test")):
            await self.run_summary(ctx, "17:05")
        self.assertIn("Hiba az OpenAI API", ctx.send.await_args.args[0])

    async def test_previous_day_and_discord_length_limit(self):
        message = SimpleNamespace(
            author=SimpleNamespace(bot=False, name="User"),
            created_at=datetime.now(timezone.utc),
            content="Hello",
        )
        ctx = self.make_context([message])
        response = SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content="x" * 5000), finish_reason="stop")]
        )
        with patch("cogs.ai.datetime", wraps=datetime) as clock:
            clock.now.return_value = datetime(2026, 11, 12, 8, 0)
            with patch("cogs.ai.client.chat.completions.create", return_value=response) as create:
                await self.run_summary(ctx, "17:05")
        self.assertEqual(create.call_args.kwargs["max_completion_tokens"], 2600)
        self.assertIn("3800 karakter", create.call_args.kwargs["messages"][0]["content"])
        self.assertIn("14.9 óra", create.call_args.kwargs["messages"][1]["content"])
        description = ctx.send.await_args.kwargs["embed"].description
        self.assertEqual(len(description), 4096)
        self.assertIn("rövidítve", description)

    async def test_token_limit_is_reported(self):
        message = SimpleNamespace(
            author=SimpleNamespace(bot=False, name="User"),
            created_at=datetime.now(timezone.utc),
            content="Hello",
        )
        ctx = self.make_context([message])
        response = SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content="Részlet"), finish_reason="length")]
        )
        with patch("cogs.ai.client.chat.completions.create", return_value=response):
            await self.run_summary(ctx, "17:05")
        self.assertIn("rövidítve", ctx.send.await_args.kwargs["embed"].description)

    async def test_empty_api_response(self):
        message = SimpleNamespace(
            author=SimpleNamespace(bot=False, name="User"),
            created_at=datetime.now(timezone.utc),
            content="Hello",
        )
        ctx = self.make_context([message])
        response = SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=None))]
        )
        with patch("cogs.ai.client.chat.completions.create", return_value=response):
            await self.run_summary(ctx, "17:05")
        self.assertIn("nem adott vissza", ctx.send.await_args.args[0])

    async def test_time_ranges_and_duration(self):
        cases = [
            ("17", "19", datetime(2026, 11, 12, 21), datetime(2026, 11, 12, 17), datetime(2026, 11, 12, 19), 900),
            ("17.05", "19:00", datetime(2026, 11, 12, 10), datetime(2026, 11, 11, 17, 5), datetime(2026, 11, 11, 19), 900),
            ("23:00", "02:00", datetime(2026, 11, 12, 8), datetime(2026, 11, 11, 23), datetime(2026, 11, 12, 2), 900),
            ("17", "17", datetime(2026, 11, 12, 21), datetime(2026, 11, 11, 17), datetime(2026, 11, 12, 17), 2600),
        ]
        for since, end, now, start, stop, tokens in cases:
            with self.subTest(since=since, end=end, now=now):
                message = SimpleNamespace(
                    author=SimpleNamespace(bot=False, name="User"),
                    created_at=now,
                    content="Hello",
                )
                ctx = self.make_context([message])
                response = SimpleNamespace(
                    choices=[SimpleNamespace(message=SimpleNamespace(content="Összefoglaló"), finish_reason="stop")]
                )
                with patch("cogs.ai.datetime", wraps=datetime) as clock:
                    clock.now.return_value = now
                    with patch("cogs.ai.client.chat.completions.create", return_value=response) as create:
                        await self.run_summary(ctx, since, end)
                self.assertEqual(ctx.channel.history_args["after"].id, discord.utils.time_snowflake(start) - 1)
                self.assertEqual(ctx.channel.history_args["before"], stop)
                self.assertEqual(create.call_args.kwargs["max_completion_tokens"], tokens)
                self.assertIn(f"{since}–{end}", ctx.send.await_args.kwargs["embed"].footer.text)

    async def test_invalid_end(self):
        ctx = self.make_context()
        await self.run_summary(ctx, "17:00", "25:00")
        self.assertIn("Hibás időpont", ctx.send.await_args.args[0])
        self.assertIsNone(ctx.channel.history_args)

    async def test_no_end_keeps_open_history(self):
        ctx = self.make_context()
        with patch("cogs.ai.datetime", wraps=datetime) as clock:
            clock.now.return_value = datetime(2026, 11, 12, 21)
            await self.run_summary(ctx, "17")
        self.assertEqual(ctx.channel.history_args["after"], datetime(2026, 11, 12, 17))
        self.assertNotIn("before", ctx.channel.history_args)

    async def test_date_ranges_and_summary_duration(self):
        cases = [
            ("2026-11-10", None, datetime(2026, 11, 10), datetime(2026, 11, 11), "24.0 óra", "2026-11-10"),
            ("2026.11.09", "2026-11-10", datetime(2026, 11, 9), datetime(2026, 11, 11), "48.0 óra", "2026.11.09–2026-11-10"),
            ("2026-11-12", None, datetime(2026, 11, 12), datetime(2026, 11, 13), "8.0 óra", "2026-11-12"),
            ("2026-11-12", "2026.11.12", datetime(2026, 11, 12), datetime(2026, 11, 13), "8.0 óra", "2026-11-12–2026.11.12"),
        ]
        for since, end, start, stop, duration, footer in cases:
            with self.subTest(since=since, end=end):
                timestamp = datetime(2026, 11, 10, 12, tzinfo=timezone.utc)
                message = SimpleNamespace(
                    author=SimpleNamespace(bot=False, name="User"),
                    created_at=timestamp,
                    content="Hello",
                )
                ctx = self.make_context([message])
                response = SimpleNamespace(
                    choices=[SimpleNamespace(message=SimpleNamespace(content="Összefoglaló"), finish_reason="stop")]
                )
                with patch("cogs.ai.datetime", wraps=datetime) as clock:
                    clock.now.return_value = datetime(2026, 11, 12, 8)
                    with patch("cogs.ai.client.chat.completions.create", return_value=response) as create:
                        await self.run_summary(ctx, since, end)
                self.assertEqual(ctx.channel.history_args["after"].id, discord.utils.time_snowflake(start) - 1)
                self.assertEqual(ctx.channel.history_args["before"], stop)
                prompt = create.call_args.kwargs["messages"][1]["content"]
                self.assertIn(duration, prompt)
                self.assertIn(timestamp.astimezone().strftime("%Y-%m-%d %H:%M:%S"), prompt)
                self.assertEqual(ctx.send.await_args.kwargs["embed"].footer.text, f"Összefoglalva: {footer}")

    async def test_invalid_date_ranges(self):
        cases = [
            ("2026-02-30", None),
            ("2026-11-10", "2026-11-09"),
            ("2026-11-13", None),
            ("2026-11-10", "2026-11-13"),
            ("2026-11-10", "19:00"),
            ("17:00", "2026-11-10"),
            ("2026-11.10", None),
        ]
        for since, end in cases:
            with self.subTest(since=since, end=end):
                ctx = self.make_context()
                with patch("cogs.ai.datetime", wraps=datetime) as clock:
                    clock.now.return_value = datetime(2026, 11, 12, 8)
                    await self.run_summary(ctx, since, end)
                self.assertIn("Hibás időpont vagy dátum", ctx.send.await_args.args[0])
                self.assertIsNone(ctx.channel.history_args)

    async def test_no_messages_on_date_reports_day(self):
        ctx = self.make_context()
        with patch("cogs.ai.datetime", wraps=datetime) as clock:
            clock.now.return_value = datetime(2026, 11, 12, 8)
            await self.run_summary(ctx, "2026-11-10")
        self.assertIn("2026-11-10 napján", ctx.send.await_args.args[0])

    async def test_slash_autocomplete_suggestions(self):
        parameters = {param.name: param for param in AI.summary.app_command.parameters}
        self.assertTrue(parameters["since"].autocomplete)
        self.assertTrue(parameters["end"].autocomplete)
        self.assertFalse(parameters["end"].required)
        with patch("cogs.ai.datetime", wraps=datetime) as clock:
            clock.now.return_value = datetime(2026, 11, 12, 8)
            dates = await summary_suggestions(None, "2026.11.1")
            hours = await summary_suggestions(None, "17")
            unfiltered = await summary_suggestions(None, "")
        self.assertIn("2026.11.12", [choice.value for choice in dates])
        self.assertIn("2026.11.10", [choice.value for choice in dates])
        self.assertEqual([choice.value for choice in hours], ["17:00"])
        self.assertLessEqual(len(unfiltered), 25)


if __name__ == "__main__":
    unittest.main()
