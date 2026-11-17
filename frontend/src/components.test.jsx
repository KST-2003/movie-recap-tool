// @vitest-environment jsdom
import React, { useState } from 'react';
import { afterEach, beforeAll, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import Select from './Select.jsx';
import Shell from './Shell.jsx';
import CaptionStyleControls from './CaptionStyleControls.jsx';
import PreviewStudio from './PreviewStudio.jsx';
import { DEFAULT_CAPTION_STYLE } from './captionFonts.js';

vi.mock('./captionFonts.js', async (importOriginal) => ({ ...(await importOriginal()), loadCaptionFont: async () => 'sans-serif' }));
beforeAll(() => { Element.prototype.scrollIntoView = vi.fn(); });
afterEach(cleanup);

describe('dropdown', () => {
  const options = [{ value: 'a', label: 'First', group: 'Choices' }, { value: 'b', label: 'Second', group: 'Choices' }];
  it('opens, selects an option, and closes', async () => {
    const change = vi.fn();
    const user = userEvent.setup();
    render(<Select value="a" onChange={change} options={options} />);
    await user.click(screen.getByRole('button', { name: 'First' }));
    expect(screen.getByRole('listbox')).toBeTruthy();
    await user.click(screen.getByRole('option', { name: 'Second' }));
    expect(change).toHaveBeenCalledWith('b');
    expect(screen.queryByRole('listbox')).toBeNull();
  });
  it('supports keyboard selection and a disabled state', async () => {
    const change = vi.fn();
    const user = userEvent.setup();
    const { rerender } = render(<Select value="a" onChange={change} options={options} />);
    screen.getByRole('button').focus();
    await user.keyboard('{ArrowDown}{ArrowDown}{Enter}');
    expect(change).toHaveBeenCalledWith('b');
    rerender(<Select value="a" onChange={change} options={options} disabled />);
    expect(screen.getByRole('button').disabled).toBe(true);
  });
});

describe('mobile navigation', () => {
  it('navigates between pages and opens and closes the account menu', async () => {
    const user = userEvent.setup();
    const setView = vi.fn();
    render(<Shell view="create" setView={setView} account={{ email: 'user@example.com', remaining_seconds: 600, daily_minutes: 10, monthly_minutes: 100 }} onLogout={vi.fn()}><div>Page content</div></Shell>);
    await user.click(within(screen.getAllByRole('navigation').at(-1)).getByRole('button', { name: 'My videos' }));
    expect(setView).toHaveBeenCalledWith('history');
    await user.click(screen.getByRole('button', { name: 'Menu' }));
    expect(screen.getByRole('button', { name: 'Close menu' })).toBeTruthy();
    await user.keyboard('{Escape}');
    expect(screen.queryByRole('button', { name: 'Close menu' })).toBeNull();
  });
});

describe('caption style controls', () => {
  it('changes position and resets the style', async () => {
    const user = userEvent.setup();
    function Harness() {
      const [style, setStyle] = useState({ ...DEFAULT_CAPTION_STYLE });
      return <CaptionStyleControls cap={style} onChange={setStyle} />;
    }
    render(<Harness />);
    await user.selectOptions(screen.getByLabelText('Position'), 'custom');
    expect(screen.getByLabelText(/Height on the screen/)).toBeTruthy();
    fireEvent.change(screen.getByLabelText(/Height on the screen/), { target: { value: '0.5' } });
    expect(screen.getByText('50%')).toBeTruthy();
    await user.click(screen.getByRole('button', { name: 'Reset style' }));
    expect(screen.queryByLabelText(/Height on the screen/)).toBeNull();
    expect(screen.getByLabelText('Position').value).toBe(DEFAULT_CAPTION_STYLE.position);
  });
  it('applies presets and updates size, opacity and text color', async () => {
    const user = userEvent.setup();
    function Harness() {
      const [style, setStyle] = useState({ ...DEFAULT_CAPTION_STYLE });
      return <CaptionStyleControls cap={style} onChange={setStyle} />;
    }
    render(<Harness />);
    await user.click(screen.getByRole('button', { name: 'White, outline only' }));
    expect(screen.getByLabelText(/^Box opacity/).value).toBe('0');
    fireEvent.change(screen.getByLabelText(/^Size/), { target: { value: '1.5' } });
    expect(screen.getByText('150%')).toBeTruthy();
    fireEvent.change(screen.getByLabelText('Text'), { target: { value: '#123456' } });
    expect(screen.getByLabelText('Text').value).toBe('#123456');
  });
  it('applies every preset and changes font, outline, box color and opacity', async () => {
    const user = userEvent.setup();
    function Harness() { const [style, setStyle] = useState({ ...DEFAULT_CAPTION_STYLE }); return <CaptionStyleControls cap={style} onChange={setStyle} />; }
    render(<Harness />);
    for (const preset of ['Yellow on dark', 'White on dark', 'White, outline only', 'Black on white']) await user.click(screen.getByRole('button', { name: preset }));
    expect(screen.getByLabelText('Box').value).toBe('#ffffff');
    await user.selectOptions(screen.getByLabelText('Font'), 'padauk');
    expect(screen.getByLabelText('Font').value).toBe('padauk');
    await user.click(screen.getByRole('checkbox', { name: 'Outline' }));
    expect(screen.getByRole('checkbox', { name: 'Outline' }).checked).toBe(true);
    fireEvent.change(screen.getByLabelText(/^Box opacity/), { target: { value: '0.35' } });
    expect(screen.getByLabelText(/^Box opacity/).value).toBe('0.35');
  });
});

describe('video preview controls', () => {
  it('adds a blur box and limits the number of boxes', async () => {
    const user = userEvent.setup();
    const fx = { aspect: 'original', fitMode: 'blur', videoSpeed: 1, brightness: 0, contrast: 1, saturation: 1, logoSize: 0.15, logoPosition: 'top-right', blurBoxes: [] };
    const change = vi.fn();
    const { rerender } = render(<PreviewStudio src="blob:test" fx={fx} onChange={change} />);
    await user.click(screen.getByRole('button', { name: '+ Blur box' }));
    expect(change.mock.calls[0][0].blurBoxes).toHaveLength(1);
    rerender(<PreviewStudio src="blob:test" fx={{ ...fx, blurBoxes: Array(6).fill({ x: 0, y: 0, w: 0.1, h: 0.1 }) }} onChange={change} />);
    expect(screen.getByRole('button', { name: '+ Blur box' }).disabled).toBe(true);
  });
  it('allows removing a logo and changing its layer order', async () => {
    const user = userEvent.setup();
    URL.createObjectURL = vi.fn(() => 'blob:logo');
    URL.revokeObjectURL = vi.fn();
    const change = vi.fn();
    const fx = { aspect: 'original', fitMode: 'blur', videoSpeed: 1, brightness: 0, contrast: 1, saturation: 1, logoSize: 0.15, logoPosition: 'top-right', blurBoxes: [] };
    render(<PreviewStudio src="blob:video" logoFile={new File(['logo'], 'logo.png', { type: 'image/png' })} fx={fx} onChange={change} />);
    await user.click(screen.getByRole('button', { name: 'Layers' }));
    await user.click(screen.getByLabelText('Logo above subtitle'));
    expect(change).toHaveBeenCalledWith({ logoOnTop: true });
    await user.click(screen.getByRole('button', { name: 'Remove logo' }));
    expect(change).toHaveBeenCalledWith({ removeLogo: true });
  });
});
