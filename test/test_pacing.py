"""频控退避的测试。

营地对账号维度限流：最小请求间隔 1200ms，命中频控后冷却 12 小时。冷却
期间再发请求会把冷却重新计时，所以不能靠重试碰运气。

这些数值来自参考实现记录的实测经验，不是腾讯公布的限额。
"""

import time

import pytest

from ainong.camp.pacing import 冷却已过, 账号频控闸, 频控闸


class Test频率闸:
    def test_第一次放行(self):
        闸 = 账号频控闸(最小间隔秒=0.0)
        assert 闸.可以发() is True

    def test_刚发过就再发要等(self):
        闸 = 账号频控闸(最小间隔秒=5.0)
        闸.记录发出()
        assert 闸.可以发() is False

    def test_间隔到了放行(self, monkeypatch):
        闸 = 账号频控闸(最小间隔秒=1.0)
        闸.记录发出()
        当前 = time.monotonic()
        monkeypatch.setattr(time, "monotonic", lambda: 当前 + 1.5)
        assert 闸.可以发() is True

    def test_重复发不重置计时(self, monkeypatch):
        """冷却期间再请求不应把计时推后，否则永远过不去。"""
        闸 = 账号频控闸(最小间隔秒=10.0)
        闸.记录发出()
        当前 = time.monotonic()
        monkeypatch.setattr(time, "monotonic", lambda: 当前 + 3.0)
        闸.记录发出()
        monkeypatch.setattr(time, "monotonic", lambda: 当前 + 11.0)
        assert 闸.可以发() is True

    def test_剩余等待随时间减少(self, monkeypatch):
        闸 = 账号频控闸(最小间隔秒=10.0)
        闸.记录发出()
        当前 = time.monotonic()
        monkeypatch.setattr(time, "monotonic", lambda: 当前 + 4.0)
        assert 闸.还需等待() == pytest.approx(6.0, abs=0.1)

    def test_没发过时不需要等(self):
        assert 账号频控闸(最小间隔秒=5.0).还需等待() == 0.0


class Test冷却:
    def test_初始不在冷却(self):
        闸 = 账号频控闸(最小间隔秒=0.0, 冷却秒=100.0)
        assert 闸.冷却中() is False

    def test_命中频控后进入冷却(self):
        闸 = 账号频控闸(最小间隔秒=0.0, 冷却秒=100.0)
        闸.记频控()
        assert 闸.冷却中() is True

    def test_冷却期间不再放行(self):
        闸 = 账号频控闸(最小间隔秒=0.0, 冷却秒=100.0)
        闸.记频控()
        assert 闸.可以发() is False

    def test_冷却过了自动放行(self, monkeypatch):
        闸 = 账号频控闸(最小间隔秒=0.0, 冷却秒=10.0)
        闸.记频控()
        当前 = time.monotonic()
        monkeypatch.setattr(time, "monotonic", lambda: 当前 + 11.0)
        assert 闸.可以发() is True

    def test_冷却剩余随时间减少(self, monkeypatch):
        闸 = 账号频控闸(最小间隔秒=0.0, 冷却秒=100.0)
        闸.记频控()
        当前 = time.monotonic()
        monkeypatch.setattr(time, "monotonic", lambda: 当前 + 40.0)
        assert 闸.冷却剩余() == pytest.approx(60.0, abs=0.1)


class Test按账号隔离:
    def test_一个账号频控不影响另一个(self):
        """账号池场景：某个号被频控时换号，而不是让所有用户一起等。"""
        闸 = 频控闸()
        甲 = 闸.取账号闸("账号A")
        乙 = 闸.取账号闸("账号B")
        甲.记频控()
        assert 甲.可以发() is False
        assert 乙.可以发() is True

    def test_同一账号拿到同一个闸(self):
        闸 = 频控闸()
        assert 闸.取账号闸("账号A") is 闸.取账号闸("账号A")

    def test_账号名不出现在错误信息里(self):
        闸 = 频控闸(最小间隔秒=0.0, 冷却秒=100.0)
        闸.取账号闸("secret-token-abc").记频控()
        提示 = 闸.取账号闸("secret-token-abc").可读提示()
        assert "secret-token-abc" not in 提示
        assert "冷却" in 提示


class Test冷却已过:
    def test_从明起到期的时刻(self):
        当前 = time.monotonic()
        到期 = 冷却已过(当前, 冷却秒=10.0)
        assert 到期 == pytest.approx(当前 + 10.0, abs=0.1)

    def test_冷却为零时就是当前(self):
        当前 = time.monotonic()
        assert 冷却已过(当前, 0.0) == 当前
