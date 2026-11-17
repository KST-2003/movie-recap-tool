// @vitest-environment jsdom
import React from 'react';
import { afterEach, beforeAll, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import VoiceLibrary from './VoiceLibrary.jsx';
import Editor from './Editor.jsx';

vi.mock('./captionFonts.js', async (original) => ({ ...(await original()), loadCaptionFont: async () => 'sans-serif' }));
beforeAll(() => { Element.prototype.scrollIntoView = vi.fn(); });
afterEach(cleanup);
const voices = [{ name: 'Kore', gender: 'female', sample_url: '/kore.wav' }, { name: 'Charon', gender: 'male', sample_url: '/charon.wav' }];

describe('voice library', () => {
  it('filters voices by category and search and selects one', async () => {
    const user = userEvent.setup(); const select = vi.fn(); const close = vi.fn(); const play = vi.fn();
    render(<VoiceLibrary voices={voices} looks={[]} selected="Kore" onSelect={select} onClose={close} onPlay={play} />);
    await user.click(screen.getByRole('button', { name: /^male 1$/i }));
    expect(screen.queryByText('Thiri')).toBeNull();
    expect(screen.getByText('Aung')).toBeTruthy();
    await user.click(screen.getByRole('button', { name: /Play/ }));
    expect(play).toHaveBeenCalledWith({ name: 'Charon', sample_url: '/charon.wav' });
    await user.click(screen.getByRole('button', { name: 'Use' }));
    expect(select).toHaveBeenCalledWith(voices[1]); expect(close).toHaveBeenCalledOnce();
    await user.type(screen.getByPlaceholderText(/Search:/), 'missing');
    expect(screen.getByText('Nothing found.')).toBeTruthy();
  });
});

describe('editor', () => {
  const project = { source_duration: 10, segments: [{ id: 1, start: 0, text: 'Original line', source_text: 'source', speaker: 'A', audio_dur: 2, applied_tempo: 1 }], speakers: { A: { voice: 'Kore', gender: 'female' } }, output: 'dub' };
  it('edits a line, changes its speed, previews and applies it', async () => {
    const user = userEvent.setup(); const apply = vi.fn(); const preview = vi.fn();
    const { container } = render(<Editor project={project} videoRef={{ current: null }} onApply={apply} onPreviewLine={preview} voices={voices} />);
    expect(screen.getByRole('button', { name: 'Apply changes & re-render' }).disabled).toBe(true);
    const text = screen.getByPlaceholderText('Burmese text for this line');
    await user.clear(text); await user.type(text, 'Changed line');
    expect(container.innerHTML).not.toMatch(/Infinity|NaN/);
    await user.click(screen.getByRole('button', { name: '1.2x' }));
    await user.click(screen.getByRole('button', { name: /Hear Thiri/ }));
    expect(preview).toHaveBeenCalledWith(expect.objectContaining({ text: 'Changed line', tempo: 1.2 }), 'Kore');
    await user.click(screen.getByRole('button', { name: 'Apply changes & re-render' }));
    expect(apply).toHaveBeenCalledWith([expect.objectContaining({ id: 1, text: 'Changed line', tempo: 1.2 })], undefined, undefined, undefined);
  });
  it('changes a character voice and can reset edits', async () => {
    const user = userEvent.setup(); const apply = vi.fn();
    render(<Editor project={project} videoRef={{ current: null }} onApply={apply} voices={voices} />);
    await user.click(screen.getByRole('button', { name: /A female/ }));
    await user.click(screen.getByRole('option', { name: /Aung \(male\)/ }));
    await user.click(screen.getByRole('button', { name: 'Apply changes & re-render' }));
    expect(apply.mock.calls[0][1]).toEqual({ A: 'Charon' });
    await user.click(screen.getByRole('button', { name: 'Reset' }));
    expect(screen.getByRole('button', { name: 'Apply changes & re-render' }).disabled).toBe(true);
  });
});
