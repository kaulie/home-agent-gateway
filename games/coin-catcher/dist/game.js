(function () {
  "use strict";

  var GAME_MESSAGE_CHANNEL = "homeagent.game";
  var VALID_TYPES = {
    START: 1, PAUSE: 1, RESUME: 1, RESTART: 1,
    MOVE_LEFT: 1, MOVE_RIGHT: 1, JUMP: 1, SPEED_UP: 1, SPEED_DOWN: 1,
  };

  function parseGameCommand(raw) {
    if (!raw || typeof raw !== "object") return null;
    var inner = raw.command && typeof raw.command === "object" ? raw.command : raw;
    var type = String(inner.type || "").toUpperCase();
    if (!VALID_TYPES[type]) return null;
    var sourceRaw = String(inner.source || "SYSTEM").toUpperCase();
    var source = sourceRaw === "VOICE" || sourceRaw === "GESTURE" ? sourceRaw : "SYSTEM";
    return { type: type, source: source, timestamp: Number(inner.timestamp || Date.now()) };
  }

  var listeners = [];
  var lastAt = {};

  function dispatch(raw) {
    var cmd = parseGameCommand(raw);
    if (!cmd) return false;
    var cd = { MOVE_LEFT: 80, MOVE_RIGHT: 80, JUMP: 200, SPEED_UP: 400, SPEED_DOWN: 400 }[cmd.type] || 0;
    if (cd > 0) {
      var prev = lastAt[cmd.type] || 0;
      if (cmd.timestamp - prev < cd) return false;
      lastAt[cmd.type] = cmd.timestamp;
    }
    for (var i = 0; i < listeners.length; i++) listeners[i](cmd);
    return true;
  }

  function subscribe(fn) {
    listeners.push(fn);
    return function () {
      var idx = listeners.indexOf(fn);
      if (idx >= 0) listeners.splice(idx, 1);
    };
  }

  // Cast transport
  window.addEventListener("message", function (ev) {
    var data = ev.data;
    if (!data || typeof data !== "object" || data.channel !== GAME_MESSAGE_CHANNEL) return;
    var cmd = parseGameCommand(data);
    if (cmd) dispatch(cmd);
  });
  if (window.parent !== window) {
    window.parent.postMessage(
      { channel: GAME_MESSAGE_CHANNEL, event: "game.loaded", game_id: "coin_catcher" },
      "*"
    );
  }

  // SSE fallback
  (function () {
    var params = new URLSearchParams(window.location.search);
    if (params.get("transport") === "cast") return;
    var url = params.get("sse") || params.get("stream") || (window.location.origin + "/events/stream");
    function connect() {
      var es;
      try { es = new EventSource(url); } catch (e) { return; }
      es.onmessage = function (ev) {
        try { dispatch(JSON.parse(ev.data)); } catch (e) {}
      };
      es.onerror = function () { es.close(); setTimeout(connect, 1500); };
    }
    connect();
  })();

  // Keyboard debug
  var keyMap = { ArrowLeft: "MOVE_LEFT", ArrowRight: "MOVE_RIGHT", Space: "JUMP", KeyP: "PAUSE", KeyR: "RESTART", Enter: "START" };
  window.addEventListener("keydown", function (ev) {
    var type = keyMap[ev.code];
    if (!type) return;
    ev.preventDefault();
    dispatch({ type: type, source: "SYSTEM", timestamp: Date.now() });
  });

  var CoinCatcherScene = Phaser.Class({
    Extends: Phaser.Scene,
    initialize: function CoinCatcherScene() {
      Phaser.Scene.call(this, { key: "CoinCatcherScene" });
      this.state = "idle";
      this.score = 0;
      this.coins = [];
      this.spawnTimer = 0;
      this.spawnInterval = 900;
      this.moveLeftUntil = 0;
      this.moveRightUntil = 0;
      this.jumpVy = 0;
      this.playerBaseY = 0;
    },
    create: function () {
      var self = this;
      var width = this.scale.width;
      var height = this.scale.height;
      this.add.rectangle(width / 2, height / 2, width, height, 0x0a1628);
      this.add.line(0, 0, 0, height - 120, width, height - 120, 0x2a4a6a, 0.8).setOrigin(0);
      this.playerBaseY = height - 180;
      this.player = this.add.rectangle(width / 2, this.playerBaseY, 100, 60, 0xffc857);
      this.physics.add.existing(this.player);
      this.playerBody = this.player.body;
      this.playerBody.setCollideWorldBounds(true);
      this.playerBody.setImmovable(true);
      this.scoreText = this.add.text(48, 40, "Score: 0", {
        fontFamily: "system-ui, PingFang SC, sans-serif", fontSize: "48px", color: "#ffffff",
      }).setScrollFactor(0);
      this.hintText = this.add.text(width / 2, height / 2 - 40, "说：开始游戏", {
        fontFamily: "system-ui, PingFang SC, sans-serif", fontSize: "42px", color: "#a8d4ff", align: "center",
      }).setOrigin(0.5).setScrollFactor(0);
      this.add.text(width / 2, height - 48, "语音 / 手势控制 · 键盘方向键调试", {
        fontFamily: "system-ui, PingFang SC, sans-serif", fontSize: "24px", color: "#6688aa",
      }).setOrigin(0.5).setScrollFactor(0);
      this.unsub = subscribe(function (cmd) { self.onCommand(cmd); });
    },
    shutdown: function () { if (this.unsub) this.unsub(); },
    onCommand: function (cmd) {
      var self = this;
      var map = {
        START: function () { self.startGame(false); },
        RESTART: function () { self.startGame(true); },
        PAUSE: function () {
          if (self.state === "playing") { self.state = "paused"; self.hintText.setText("已暂停 · 说：继续"); }
        },
        RESUME: function () {
          if (self.state === "paused") { self.state = "playing"; self.hintText.setText(""); }
        },
        MOVE_LEFT: function () { self.moveLeftUntil = self.time.now + 400; },
        MOVE_RIGHT: function () { self.moveRightUntil = self.time.now + 400; },
        JUMP: function () {
          if (self.state === "playing" && Math.abs(self.jumpVy) < 10) self.jumpVy = -520;
        },
        SPEED_UP: function () { self.spawnInterval = Math.max(400, self.spawnInterval * 0.85); },
        SPEED_DOWN: function () { self.spawnInterval = Math.min(1600, self.spawnInterval * 1.15); },
      };
      if (map[cmd.type]) map[cmd.type]();
    },
    startGame: function (reset) {
      if (reset) this.clearCoins();
      this.score = 0;
      this.scoreText.setText("Score: 0");
      this.spawnInterval = 900;
      this.state = "playing";
      this.hintText.setText("");
      this.player.x = this.scale.width / 2;
      this.player.y = this.playerBaseY;
      this.jumpVy = 0;
      this.spawnTimer = 0;
    },
    clearCoins: function () {
      for (var i = 0; i < this.coins.length; i++) this.coins[i].sprite.destroy();
      this.coins = [];
    },
    spawnCoin: function () {
      var margin = 80;
      var x = margin + Math.random() * (this.scale.width - margin * 2);
      var sprite = this.add.circle(x, -20, 22, 0xffd700).setStrokeStyle(3, 0xffaa00);
      this.coins.push({ sprite: sprite, vy: 180 + Math.random() * 120 });
    },
    update: function (_time, delta) {
      if (this.state !== "playing") return;
      var dt = delta / 1000;
      var speed = 420;
      if (this.time.now < this.moveLeftUntil) this.player.x -= speed * dt;
      if (this.time.now < this.moveRightUntil) this.player.x += speed * dt;
      this.player.x = Phaser.Math.Clamp(this.player.x, 60, this.scale.width - 60);
      this.jumpVy += 980 * dt;
      this.player.y += this.jumpVy * dt;
      if (this.player.y >= this.playerBaseY) { this.player.y = this.playerBaseY; this.jumpVy = 0; }
      this.spawnTimer += delta;
      if (this.spawnTimer >= this.spawnInterval) { this.spawnTimer = 0; this.spawnCoin(); }
      var catchY = this.player.y - 20;
      var catchX = this.player.x;
      var catchR = 55;
      for (var i = this.coins.length - 1; i >= 0; i--) {
        var c = this.coins[i];
        c.sprite.y += c.vy * dt;
        var dx = c.sprite.x - catchX;
        var dy = c.sprite.y - catchY;
        if (dx * dx + dy * dy < catchR * catchR) {
          this.score += 10;
          this.scoreText.setText("Score: " + this.score);
          c.sprite.destroy();
          this.coins.splice(i, 1);
          continue;
        }
        if (c.sprite.y > this.scale.height + 40) {
          c.sprite.destroy();
          this.coins.splice(i, 1);
        }
      }
    },
  });

  var BootScene = Phaser.Class({
    Extends: Phaser.Scene,
    initialize: function BootScene() { Phaser.Scene.call(this, { key: "BootScene" }); },
    create: function () { this.scene.start("CoinCatcherScene"); },
  });

  new Phaser.Game({
    type: Phaser.AUTO,
    parent: "game",
    width: 1920,
    height: 1080,
    backgroundColor: "#0a1628",
    scale: { mode: Phaser.Scale.FIT, autoCenter: Phaser.Scale.CENTER_BOTH },
    physics: { default: "arcade", arcade: { gravity: { x: 0, y: 0 } } },
    scene: [BootScene, CoinCatcherScene],
  });
})();
