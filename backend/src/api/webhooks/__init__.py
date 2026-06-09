"""Пакет webhook-подписок и доставки событий kb-support (E10-8, #198; ADR-0015).

PR-A (#198): таблица подписок `WebhookSubscription` + admin-CRUD (`GET/POST /webhooks`,
scope=`staff_admin`) + HMAC-signer исходящих событий (`signing.py`). Эмиссия событий и
врезки — PR-B; приём webhook страховщика — PR-C.

Арх-константа: своя БД (без FK к чужим), связь с подписчиками только по HTTP (PR-B).
"""
