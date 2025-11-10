# Audio Stream Handling Analysis - VakClient

## Summary
**Status: ✅ FIXED**

The audio stream handling has been completely rewritten to properly handle streaming transcription.

---

## Critical Issues Found

### 1. **CRITICAL: Each Audio Chunk Creates New Transcription Session**

**Location:** `VakServer/src/routes/message-handlers.ts` lines 130-177

**Problem:**
- Every time a 100ms audio chunk arrives, `handleAudioStream()` creates a **new** `StartStreamTranscriptionCommand`
- The Readable stream immediately ends after pushing the single chunk (`this.push(null)`)
- This means AWS Transcribe receives a new session for each chunk, not a continuous stream
- Transcribe cannot properly transcribe audio split across multiple sessions

**Current Code:**
```typescript
export async function handleAudioStream(...) {
  const audioStream = new Readable({
    read() {
      this.push(audioData);  // Push single chunk
      this.push(null);        // End stream immediately ❌
    },
  });
  
  const command = new StartStreamTranscriptionCommand({...});
  await transcribeClient.send(command);  // New session for each chunk ❌
}
```

**Expected Behavior:**
- One transcription session per recording session
- Audio chunks should be appended to an ongoing stream
- Stream should only end when recording stops

---

### 2. **No Persistent Stream Management**

**Problem:**
- No mechanism to maintain a single transcription stream per WebSocket connection
- No way to track if a transcription session is already active
- No cleanup when recording stops

**Impact:**
- Cannot properly stream audio to AWS Transcribe
- Each chunk is treated as a separate, complete audio file

---

### 3. **Client-Side: Blob Handling**

**Location:** `VakClient/src/App.tsx` line 154

**Current Code:**
```typescript
mediaRecorder.ondataavailable = (event) => {
  if (event.data.size > 0 && wsRef.current?.readyState === WebSocket.OPEN) {
    wsRef.current.send(event.data);  // Sends Blob directly
  }
};
```

**Status:** ✅ This is actually correct - WebSocket.send() handles Blob objects properly

**Potential Issue:**
- No error handling if send fails
- No logging to debug audio transmission

---

### 4. **Server-Side: Binary Message Handling**

**Location:** `VakServer/src/websocket-handler.ts` lines 53-67

**Current Code:**
```typescript
else if (Buffer.isBuffer(message)) {
  // Try to parse as JSON first
  try {
    const text = message.toString('utf-8');
    const data = JSON.parse(text);
    // ... handle JSON
  } catch (e) {
    // Not JSON, treat as binary audio
    await handleAudioStream(connectionId, message, fastify, sendToClientLocal);
  }
}
```

**Status:** ✅ Correctly identifies binary audio and routes to handler

**Issue:** The handler itself is broken (see Issue #1)

---

## How AWS Transcribe Streaming Should Work

AWS Transcribe Streaming expects:
1. **One session** per audio stream
2. **AsyncIterable** of `AudioStream` events
3. Each event should be an `AudioEvent` with audio data
4. Stream continues until explicitly ended

**Correct Pattern:**
```typescript
// Create stream once per recording session
const audioStream = async function* () {
  // Send configuration event first
  yield { ConfigurationEvent: { ... } };
  
  // Then send audio chunks as they arrive
  while (recording) {
    const chunk = await getNextAudioChunk();
    yield { AudioEvent: { AudioChunk: chunk } };
  }
};

// Start transcription once
const command = new StartStreamTranscriptionCommand({
  AudioStream: audioStream(),
  // ... other params
});
```

---

## Fixes Implemented ✅

### 1. **Persistent Stream Management**
   - ✅ Created `transcriptionSessions` Map to track active sessions per connection
   - ✅ Added `startTranscriptionSession()` function to initialize streams
   - ✅ Added `stopTranscriptionSession()` function to clean up streams
   - ✅ Chunks are appended to existing session instead of creating new ones

### 2. **Proper Audio Stream Format**
   - ✅ Implemented async generator that yields `AudioEvent` objects
   - ✅ Single AsyncIterable per recording session
   - ✅ Stream properly ends when recording stops (with timeout safety)

### 3. **Error Handling & Cleanup**
   - ✅ AbortController for graceful cancellation
   - ✅ Error handling in transcription promise
   - ✅ Cleanup on WebSocket disconnect and errors
   - ✅ Timeout-based force cleanup if session doesn't end naturally

### 4. **Client-Server Coordination**
   - ✅ Client sends `start-recording` signal before sending audio
   - ✅ Client sends `stop-recording` signal when done
   - ✅ Server handles both WebSocket and API Gateway routes
   - ✅ Proper state management on both sides

### 5. **Logging**
   - ✅ Logs when transcription sessions start/stop
   - ✅ Logs transcription results
   - ✅ Logs errors with connection context

---

## Testing Checklist

- [ ] Single audio chunk transcription
- [ ] Multiple chunks in one recording session
- [ ] Recording start/stop lifecycle
- [ ] Multiple concurrent connections
- [ ] Error handling (network issues, AWS errors)
- [ ] Stream cleanup on disconnect

---

## Files Changed ✅

1. **VakServer/src/routes/message-handlers.ts**
   - ✅ Complete rewrite of `handleAudioStream()`
   - ✅ Added `startTranscriptionSession()` function
   - ✅ Added `stopTranscriptionSession()` function
   - ✅ Added stream management infrastructure

2. **VakServer/src/websocket-handler.ts**
   - ✅ Added handling for `start-recording` and `stop-recording` signals
   - ✅ Cleanup transcription sessions on disconnect/error

3. **VakServer/src/routes/default.ts**
   - ✅ Added handling for `start-recording` and `stop-recording` signals (API Gateway)

4. **VakClient/src/App.tsx**
   - ✅ Sends `start-recording` signal before recording
   - ✅ Sends `stop-recording` signal when stopping
   - ✅ Added error handling for audio chunk sending
   - ✅ Handles `recording-started` and `recording-stopped` messages
