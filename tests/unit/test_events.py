import asyncio

from app.events import EventBus


def run(coro):
    return asyncio.run(coro)


def test_exact_subscription_receives_event():
    bus = EventBus()
    got = []
    bus.subscribe("card.blocked", lambda e: got.append(e))
    run(bus.publish("card.blocked", {"card": "1234"}))
    assert len(got) == 1
    assert got[0].topic == "card.blocked"
    assert got[0].payload == {"card": "1234"}
    assert got[0].id and got[0].timestamp


def test_non_matching_topic_not_delivered():
    bus = EventBus()
    got = []
    bus.subscribe("card.blocked", lambda e: got.append(e))
    run(bus.publish("card.activated", {}))
    assert got == []


def test_wildcard_and_prefix_patterns():
    bus = EventBus()
    everything, calls = [], []
    bus.subscribe("*", lambda e: everything.append(e.topic))
    bus.subscribe("call.*", lambda e: calls.append(e.topic))
    run(bus.publish("call.started", {}))
    run(bus.publish("card.blocked", {}))
    assert everything == ["call.started", "card.blocked"]
    assert calls == ["call.started"]


def test_async_and_sync_handlers_both_work():
    bus = EventBus()
    seen = []

    async def async_handler(e):
        await asyncio.sleep(0)
        seen.append(("async", e.topic))

    bus.subscribe("x.y", async_handler)
    bus.subscribe("x.y", lambda e: seen.append(("sync", e.topic)))
    run(bus.publish("x.y", {}))
    assert ("async", "x.y") in seen and ("sync", "x.y") in seen


def test_handlers_run_in_subscription_order():
    bus = EventBus()
    order = []
    bus.subscribe("t", lambda e: order.append(1))
    bus.subscribe("t", lambda e: order.append(2))
    bus.subscribe("t", lambda e: order.append(3))
    run(bus.publish("t", {}))
    assert order == [1, 2, 3]


def test_failing_handler_does_not_block_others_and_is_dead_lettered():
    bus = EventBus()
    ok = []

    def boom(e):
        raise RuntimeError("handler exploded")

    bus.subscribe("t", boom)
    bus.subscribe("t", lambda e: ok.append(e.topic))
    run(bus.publish("t", {"a": 1}))
    assert ok == ["t"]
    assert len(bus.dead_letters) == 1
    assert "handler exploded" in bus.dead_letters[0]["error"]
    assert bus.dead_letters[0]["topic"] == "t"


def test_unsubscribe_stops_delivery():
    bus = EventBus()
    got = []
    unsubscribe = bus.subscribe("t", lambda e: got.append(1))
    run(bus.publish("t", {}))
    unsubscribe()
    run(bus.publish("t", {}))
    assert got == [1]


def test_publish_with_no_subscribers_is_safe_and_counted():
    bus = EventBus()
    run(bus.publish("nobody.listens", {}))
    assert bus.published_count == 1


def test_publish_many_preserves_order():
    bus = EventBus()
    topics = []
    bus.subscribe("*", lambda e: topics.append(e.topic))
    run(bus.publish_many([("a", {}), ("b", {}), ("c", {})]))
    assert topics == ["a", "b", "c"]
