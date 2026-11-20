/*
 * UNIVERSAL FIRMWARE DÀNH CHO 6 NODE ESP32-S3 (CÓ ĂNG TEN)
 * Đề tài: Hệ thống phát hiện bất thường trong lưu lượng truyền thông IoT
 *
 * CẤU HÌNH CHO NODE 1 (ESP32_01):
 * - Wi-Fi Hotspot: phuanh / 0123456789
 * - Raspberry Pi 5 IP: 192.168.137.35:1883
 */

#include <Arduino.h>
#include <WiFi.h>
#include <PubSubClient.h>

// ====================================================================
// 1. CẤU HÌNH NODE & MẠNG
// ====================================================================
#define NODE_ID 6  // Thay đổi thành 1, 2, 3, 4, 5, 6 cho từng board

// Thông tin Wi-Fi Hotspot do máy tính phát ra
const char* ssid = "phuanh";
const char* password = "0123456789";

// Địa chỉ IP của Raspberry Pi 5 trong mạng Hotspot
const char* mqtt_server = "192.168.137.35";
const int mqtt_port = 1883;

// Chân nút nhấn BOOT trên ESP32-S3 (GPIO 0)
#define BUTTON_BOOT_PIN 0

// Chân kết nối tới module âm thanh DFPlayer / PAM8403 (từ bài cũ):
// Tránh xung đột phần cứng: GPIO 2 trước đây bị dùng làm LED_PIN làm chập xung với chân TX DFPlayer!
#define DFPLAYER_TX_PIN 1  // Nối sang Pin 2 (RX) của DFPlayer
#define DFPLAYER_RX_PIN 2  // Nối sang Pin 3 (TX) của DFPlayer
#define LED_PIN -1         // Không dùng GPIO 2 làm LED để tránh giật áp vào màng loa

// ====================================================================
// 2. KHỞI TẠO BIẾN TOÀN CỤC
// ====================================================================
WiFiClient espClient;
PubSubClient client(espClient);

char device_id[20];
char telemetry_topic[50];
char control_topic[50];
char heartbeat_topic[50];

enum Scenario {
    TH0_NORMAL = 0,
    TH1_HIGH_RATE = 1,
    TH2_LARGE_PAYLOAD = 2,
    TH3_RECONNECT = 3,
    TH4_SILENCE = 4,
    TH5_BURST = 5,
    TH6_AUTH_FAIL = 6
};

Scenario current_scenario = TH0_NORMAL;
unsigned long last_publish_time = 0;
unsigned long last_button_press = 0;
unsigned long packet_seq = 0;
int burst_counter = 0;

// Chuỗi dummy padding tạo gói lớn cho TH2 (~1.5 KB)
const char* DUMMY_PADDING = 
    "LoremIpsumDolorSitAmetConsecteturAdipiscingElitSedDoEiusmodTemporIncididuntUtLaboreEt"
    "DoloreMagnaAliquaUtEnimAdMinimVeniamQuisNostrudExercitationUllamcoLaborisNisiUtAliquip"
    "ExEaCommodoConsequatDuisAuteIrureDolorInReprehenderitInVoluptateVelitEsseCillumDolore"
    "EuFugiatNullaPariaturExcepteurSintOccaecatCupidatatNonProidentSuntInCulpaQuiOfficia"
    "DeseruntMollitAnimIdEstLaborum12345678901234567890123456789012345678901234567890"
    "LoremIpsumDolorSitAmetConsecteturAdipiscingElitSedDoEiusmodTemporIncididuntUtLaboreEt"
    "DoloreMagnaAliquaUtEnimAdMinimVeniamQuisNostrudExercitationUllamcoLaborisNisiUtAliquip"
    "ExEaCommodoConsequatDuisAuteIrureDolorInReprehenderitInVoluptateVelitEsseCillumDolore"
    "EuFugiatNullaPariaturExcepteurSintOccaecatCupidatatNonProidentSuntInCulpaQuiOfficia"
    "DeseruntMollitAnimIdEstLaborum12345678901234567890123456789012345678901234567890"
    "LoremIpsumDolorSitAmetConsecteturAdipiscingElitSedDoEiusmodTemporIncididuntUtLaboreEt"
    "DoloreMagnaAliquaUtEnimAdMinimVeniamQuisNostrudExercitationUllamcoLaborisNisiUtAliquip"
    "ExEaCommodoConsequatDuisAuteIrureDolorInReprehenderitInVoluptateVelitEsseCillumDolore"
    "EuFugiatNullaPariaturExcepteurSintOccaecatCupidatatNonProidentSuntInCulpaQuiOfficia"
    "DeseruntMollitAnimIdEstLaborum12345678901234567890123456789012345678901234567890";

// ====================================================================
// 3. HÀM XỬ LÝ LỆNH ĐIỀU KHIỂN TỪ XA QUA MQTT
// ====================================================================
void mqtt_callback(char* topic, byte* message, unsigned int length) {
    String msg;
    for (unsigned int i = 0; i < length; i++) {
        msg += (char)message[i];
    }
    Serial.printf("[MQTT CMD] Nhan lenh tu topic %s: %s\n", topic, msg.c_str());

    if (msg.indexOf("TH0") >= 0) current_scenario = TH0_NORMAL;
    else if (msg.indexOf("TH1") >= 0) current_scenario = TH1_HIGH_RATE;
    else if (msg.indexOf("TH2") >= 0) current_scenario = TH2_LARGE_PAYLOAD;
    else if (msg.indexOf("TH3") >= 0) current_scenario = TH3_RECONNECT;
    else if (msg.indexOf("TH4") >= 0) current_scenario = TH4_SILENCE;
    else if (msg.indexOf("TH5") >= 0) current_scenario = TH5_BURST;
    else if (msg.indexOf("TH6") >= 0) current_scenario = TH6_AUTH_FAIL;

    Serial.printf("--> Da chuyen sang kich ban: TH%d\n", (int)current_scenario);
}

// ====================================================================
// 4. KẾT NỐI WIFI VÀ MQTT
// ====================================================================
void setup_wifi() {
    delay(10);
    Serial.println();
    Serial.print("Dang ket noi toi Wi-Fi: ");
    Serial.println(ssid);

    WiFi.disconnect(true);
    delay(200);
    WiFi.mode(WIFI_STA);
    WiFi.setSleep(false);

    Serial.println("[Wi-Fi] Dang quet mang xung quanh...");
    int n = WiFi.scanNetworks();
    Serial.printf("[Wi-Fi] Tim thay %d mang:\n", n);
    for (int i = 0; i < n; ++i) {
        Serial.printf("  - %s (RSSI: %d dBm, Ch: %d)\n", WiFi.SSID(i).c_str(), WiFi.RSSI(i), WiFi.channel(i));
    }

    WiFi.onEvent([](WiFiEvent_t event, WiFiEventInfo_t info){
        if (event == ARDUINO_EVENT_WIFI_STA_DISCONNECTED) {
            Serial.printf("\n[WiFi] Ngat ket noi, ma ly do (reason code): %d\n", info.wifi_sta_disconnected.reason);
        }
    });

    WiFi.begin(ssid, password);

    int attempts = 0;
    while (WiFi.status() != WL_CONNECTED && attempts < 30) {
        delay(500);
        Serial.print(".");
        attempts++;
    }

    if (WiFi.status() == WL_CONNECTED) {
        Serial.println("\n[Wi-Fi] Da ket noi thanh cong!");
        Serial.print("IP Address: ");
        Serial.println(WiFi.localIP());
        Serial.print("MAC Address: ");
        Serial.println(WiFi.macAddress());
    } else {
        Serial.println("\n[Wi-Fi] Ket noi that bai, thu lai sau...");
    }
}

void reconnect_mqtt() {
    while (!client.connected()) {
        Serial.print("Dang ket noi MQTT Broker (");
        Serial.print(mqtt_server);
        Serial.print(")...");

        bool connected = false;
        if (current_scenario == TH6_AUTH_FAIL) {
            connected = client.connect(device_id, "wrong_user", "wrong_pass");
        } else {
            connected = client.connect(device_id);
        }

        if (connected) {
            Serial.println(" Thanh cong!");
            client.subscribe(control_topic);
            client.subscribe("wievac/control/all");
            client.publish(heartbeat_topic, "online");
        } else {
            Serial.print(" That bai, rc=");
            Serial.print(client.state());
            Serial.println(" Thu lai sau 3 giay...");
            delay(3000);
            if (current_scenario != TH6_AUTH_FAIL) break;
        }
    }
}

// ====================================================================
// 5. GỬI DỮ LIỆU TELEMETRY
// ====================================================================
void send_telemetry(bool large_payload) {
    packet_seq++;
    float temp = 25.0 + (random(0, 100) / 10.0);
    float humidity = 60.0 + (random(0, 150) / 10.0);
    unsigned long uptime = millis() / 1000;

    char payload[1800];
    if (large_payload) {
        snprintf(payload, sizeof(payload), 
            "{\"id\":\"%s\",\"seq\":%lu,\"uptime\":%lu,\"temp\":%.2f,\"hum\":%.2f,\"scenario\":\"TH2_LARGE\",\"padding\":\"%s\"}",
            device_id, packet_seq, uptime, temp, humidity, DUMMY_PADDING);
    } else {
        snprintf(payload, sizeof(payload), 
            "{\"id\":\"%s\",\"seq\":%lu,\"uptime\":%lu,\"temp\":%.2f,\"hum\":%.2f,\"scenario\":\"TH%d\"}",
            device_id, packet_seq, uptime, temp, humidity, (int)current_scenario);
    }

    client.publish(telemetry_topic, payload);
    if (LED_PIN >= 0) {
        digitalWrite(LED_PIN, HIGH);
        delay(10);
        digitalWrite(LED_PIN, LOW);
    }
}

// ====================================================================
// 6. SETUP VÀ LOOP CHÍNH
// ====================================================================
void setup() {
    Serial.begin(115200);
    pinMode(BUTTON_BOOT_PIN, INPUT_PULLUP);

    // DẬP NHIỄU MẠCH ÂM THANH DFPLAYER & PAM8403 (TỪ PHẦN CỨNG BÀI CŨ):
    // 1. Gửi lệnh Sleep cho DFPlayer để tắt hẳn đầu ra DAC
    Serial1.begin(9600, SERIAL_8N1, DFPLAYER_RX_PIN, DFPLAYER_TX_PIN);
    delay(50);
    byte df_sleep_cmd[] = {0x7E, 0xFF, 0x06, 0x0A, 0x00, 0x00, 0x00, 0xFE, 0xF1, 0xEF};
    Serial1.write(df_sleep_cmd, sizeof(df_sleep_cmd));
    delay(50);
    Serial1.end();

    // 2. Ghim chân TX DFPlayer (GPIO 1) ở mức HIGH (UART IDLE) tránh nhận rác
    pinMode(DFPLAYER_TX_PIN, OUTPUT);
    digitalWrite(DFPLAYER_TX_PIN, HIGH);

    // 3. Đưa chân GPIO 2 về INPUT trở kháng an toàn, TUYỆT ĐỐI không làm OUTPUT để tránh chập chân TX của DFPlayer
    pinMode(DFPLAYER_RX_PIN, INPUT);

    if (LED_PIN >= 0) {
        pinMode(LED_PIN, OUTPUT);
        digitalWrite(LED_PIN, LOW);
    }

    snprintf(device_id, sizeof(device_id), "esp32_%02d", NODE_ID);
    snprintf(telemetry_topic, sizeof(telemetry_topic), "wievac/%s/telemetry", device_id);
    snprintf(control_topic, sizeof(control_topic), "wievac/control/%s", device_id);
    snprintf(heartbeat_topic, sizeof(heartbeat_topic), "wievac/%s/heartbeat", device_id);

    current_scenario = TH0_NORMAL; // Mặc định chạy bình thường

    Serial.println("\n==============================================");
    Serial.printf(" KHOI DONG THIET BI: %s (NODE %d)\n", device_id, NODE_ID);
    Serial.printf(" Kich ban mac dinh ban dau: TH%d\n", (int)current_scenario);
    Serial.println(" Bam nut BOOT de chuyen kich ban thu nghiem.");
    Serial.println("==============================================");

    setup_wifi();
    client.setServer(mqtt_server, mqtt_port);
    client.setCallback(mqtt_callback);
    client.setBufferSize(2048);
}

void loop() {
    if (WiFi.status() != WL_CONNECTED) {
        setup_wifi();
    }

    if (!client.connected()) {
        reconnect_mqtt();
    }
    client.loop();

    // Kiểm tra nút nhấn BOOT đổi kịch bản
    if (digitalRead(BUTTON_BOOT_PIN) == LOW) {
        if (millis() - last_button_press > 400) {
            last_button_press = millis();
            int next_sc = ((int)current_scenario + 1) % 7;
            current_scenario = (Scenario)next_sc;
            Serial.printf("\n[NUT BAM] Da chuyen sang kich ban: TH%d\n", (int)current_scenario);
        }
    }

    unsigned long now = millis();

    switch (current_scenario) {
        case TH0_NORMAL:
            if (now - last_publish_time >= 2000) {
                last_publish_time = now;
                send_telemetry(false);
                Serial.printf("[TH0 Normal] Gui goi %lu\n", packet_seq);
            }
            break;

        case TH1_HIGH_RATE:
            if (now - last_publish_time >= 65) {
                last_publish_time = now;
                send_telemetry(false);
            }
            break;

        case TH2_LARGE_PAYLOAD:
            if (now - last_publish_time >= 2000) {
                last_publish_time = now;
                send_telemetry(true);
                Serial.printf("[TH2 Large] Gui goi lon %lu (~1.5 KB)\n", packet_seq);
            }
            break;

        case TH3_RECONNECT:
            if (now - last_publish_time >= 3000) {
                last_publish_time = now;
                send_telemetry(false);
                Serial.println("[TH3 Reconnect] Co y ngat ket noi MQTT...");
                client.disconnect();
            }
            break;

        case TH4_SILENCE:
            break;

        case TH5_BURST:
            if (burst_counter < 20) {
                if (now - last_publish_time >= 50) {
                    last_publish_time = now;
                    send_telemetry(false);
                    burst_counter++;
                }
            } else {
                if (now - last_publish_time >= 5000) {
                    burst_counter = 0;
                }
            }
            break;

        case TH6_AUTH_FAIL:
            if (client.connected()) {
                client.disconnect();
            }
            delay(2000);
            reconnect_mqtt();
            break;
    }
}

