import express from 'express';
import { Readable } from 'node:stream';
import { ElevenLabsClient } from '@elevenlabs/elevenlabs-js';

const apiKey = process.env.ELEVENLABS_API_KEY;
if (!apiKey) {
  throw new Error('ELEVENLABS_API_KEY must be set before starting the TTS server.');
}

const client = new ElevenLabsClient({ apiKey });
const app = express();
app.use(express.json({ limit: '32kb' }));

const voices = {
  su: 'NBISYoQ4SVxq8eZxoHlV',
};

app.post('/api/tts', async (req, res) => {
  const text = typeof req.body?.text === 'string' ? req.body.text.trim() : '';
  const voiceId = voices[req.body?.voice] || req.body?.voiceId || process.env.ELEVENLABS_VOICE_ID;

  if (!text) {
    return res.status(400).json({ error: 'Request body must include non-empty text.' });
  }
  if (text.length > 10_000) {
    return res.status(413).json({ error: 'Text exceeds the Eleven v4 10,000 character limit.' });
  }
  if (typeof voiceId !== 'string' || !voiceId.trim()) {
    return res.status(400).json({
      error: 'Set ELEVENLABS_VOICE_ID or provide voiceId in the request body.',
    });
  }

  try {
    const audio = await client.textToSpeech.convert(voiceId, {
      text,
      modelId: 'eleven_v4',
      languageCode: 'my',
      outputFormat: 'mp3_44100_128',
    });

    res.setHeader('Content-Type', 'audio/mpeg');
    res.setHeader('Content-Disposition', 'inline; filename="burmese-voiceover.mp3"');
    Readable.fromWeb(audio).on('error', (error) => {
      console.error('[ElevenLabs TTS stream]', error);
      res.destroy(error);
    }).pipe(res);
  } catch (error) {
    console.error('[ElevenLabs TTS]', error);
    if (!res.headersSent) {
      const detail = error?.body?.detail?.message || error?.body?.detail || error?.message || String(error);
      res.status(502).json({
        error: 'ElevenLabs speech generation failed.',
        upstreamStatus: error?.statusCode,
        detail: typeof detail === 'string' ? detail : JSON.stringify(detail),
      });
    } else {
      res.destroy(error);
    }
  }
});

const port = Number(process.env.PORT || 8001);
const host = process.env.HOST || '127.0.0.1';
app.listen(port, host, () => {
  console.log(`ElevenLabs TTS endpoint listening at http://${host}:${port}`);
});
