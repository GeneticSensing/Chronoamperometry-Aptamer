/*
  MUX Channel Switching with Teensy and Raspberry Pi

  This program interfaces with a Teensy microcontroller to control an ADG731 multiplexer (MUX).
  It listens for a signal from a Raspberry Pi to change the MUX channel and acknowledges each change.

  Modified by 21 Feb 2025
  by Sadman Sakib, Adam Mak
*/

#include <SPI.h>

// RPi Communication Pins
#define CH_CHANGE_PIN      18  // Teensy IN: Command to change MUX channel
#define WE_CHANGE_ACK_PIN  21  // Teensy OUT: Acknowledge working electrode change
#define CH_CHANGE_ACK_PIN  19  // Teensy OUT: Acknowledge chip change
#define CYCLE_ACK_PIN      20  // Teensy OUT: Acknowledge full electrode change cycle

// SPI Slave Select Pin
#define SELECT_PIN1        9   // SYNC signal for the ADG731 MUX

// SPI Configuration
#define SPI_FREQUENCY      30000000
#define SPI_BIT_ORDER      MSBFIRST
#define SPI_MODE           SPI_MODE2
SPISettings spiConfig(SPI_FREQUENCY, SPI_BIT_ORDER, SPI_MODE);

// TODO: Modify data structure of channels to differentiate chips and their respective WE's from others.
// Can probably use a map via 2D array with lookup as CHANNELS[chip_id][WE_id].
// The map will be sparsely populated, but still efficient if each ID is only a byte long.

// ADG731 SPI Channel Select Addresses (MSB:: !EN !CS X A4 A3 A2 A1 A0 :: LSB)
const byte CHANNELS[] = {
  0b00011111,  // 32
  0b00011110,  // 31
  0b00011101,  // 30
  0b00011100,  // 29
  0b00011011,  // 28
  0b00011010,  // 27
  0b00011001,  // 26
  0b00011000   // 25
};

#define TOTAL_CHANNELS 8
#define MUX_OFF        0b1000000  // All switches off
#define KEEP_CHANNEL   0b01000000 // Retain previous switch condition

volatile bool triggerFunction = false;  // Flag to indicate interrupt occurrence
int channelIndex = 0; // Current channel index

// Interrupt Service Routine (ISR) for channel change signal
void handleInterrupt() {
  triggerFunction = true;
}

// Latch function to retain the previous switch condition
void latch() {
  SPI.beginTransaction(spiConfig);
  digitalWrite(SELECT_PIN1, LOW);
  SPI.transfer(KEEP_CHANNEL);
  digitalWrite(SELECT_PIN1, HIGH);
  SPI.endTransaction();
}

// Switch WE
void switchWE() {
  ;
}

// Switch MUX channel
void switchChannel(int channel) {
  SPI.beginTransaction(spiConfig);
  digitalWrite(SELECT_PIN1, LOW);
  SPI.transfer(CHANNELS[channel]);
  digitalWrite(SELECT_PIN1, HIGH);
  SPI.endTransaction();
}

void changeAck(int pin, char[] message) {
  digitalWrite(pin, HIGH);
  delay(10);
  digitalWrite(pin, LOW);
  Serial.println(channelIndex);
  Serial.println(message);
  delay(1000);
}

// Acknowledgment signal that WE has changed
void weChangeAck() {
  digitalWrite(WE_CHANGE_ACK_PIN, HIGH);
  delay(10);
  digitalWrite(WE_CHANGE_ACK_PIN, LOW);
  Serial.println(channelIndex);
  Serial.println("WE Changed!");
  delay(1000);
}

void setup() {
  // Initialize Raspberry Pi Communication Pins
  pinMode(CH_CHANGE_PIN, INPUT);
  pinMode(WE_CHANGE_ACK_PIN, OUTPUT);
  pinMode(CH_CHANGE_ACK_PIN, OUTPUT);
  pinMode(CYCLE_ACK_PIN, OUTPUT);

  // Initialize SPI Slave Select Pin
  pinMode(SELECT_PIN1, OUTPUT);

  // Attach interrupt for channel change request
  attachInterrupt(digitalPinToInterrupt(CH_CHANGE_PIN), handleInterrupt, RISING);

  // Initialize SPI and Serial Communication
  SPI.begin();
  Serial.begin(38400);

  // Initialize MUX to the first channel
  switchChannel(0);

  latch();
}

void loop() {
  // Check if an interrupt has occurred
  if (triggerFunction) {
    triggerFunction = false;  // Reset the flag
    Serial.println("Teensy: Sending instruction to MUX");
    // Cycle through channels
    channelIndex = (channelIndex + 1) % TOTAL_CHANNELS;
    // Send new channel selection to MUX
    switchChannel(channelIndex);

    // TODO: Add logic to figure out if chip has been changed
    // If not, send WE change signal, otherwise send chip/channel change signal
    
    if (channelIndex == TOTAL_CHANNELS - 1) {
      // Acknowledgment signal that MUX has cycled through all available WE's and chips
      Serial.println("Teensy: Full cycle completed. Sending signal to RPi to finish last measurement.");
      changeAck(CYCLE_ACK_PIN, "Cycle Completed!");
    } else {
      // Acknowledgment signal that the chip has changed
      Serial.println("Teensy: Completed. Sending signal to RPi to start next measurement.");
      changeAck(CH_CHANGE_ACK_PIN, "Channel Changed!");
    }
    latch();
  }
}
