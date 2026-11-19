// @vitest-environment jsdom
// Android / iOS: nothing in the Create flow may be drawn under the status bar. jsdom has no layout, so these tests pin down the pieces that
// keep the space clear (the real layout was measured in headless Chrome with a simulated status bar: see CLAUDE.md, "Status bar").
import React from 'react';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { afterEach, beforeAll, describe, expect, it, vi } from 'vitest';
import { cleanup, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import Select from './Select.jsx';
import Shell from './Shell.jsx';
import VoiceLibrary from './VoiceLibrary.jsx';

vi.mock('./safeArea.js', () => ({ safeInsets: () => ({ top: 40, bottom: 20 }) }));   // a tall status bar and a gesture bar
beforeAll(() => { Element.prototype.scrollIntoView = vi.fn(); });
afterEach(() => { cleanup(); vi.restoreAllMocks(); });

const rect = (top, bottom) => ({ top, bottom, left: 20, right: 220, width: 200, height: bottom - top, x: 20, y: top, toJSON() {} });
const setViewport = (h) => Object.defineProperty(window, 'innerHeight', { value: h, configurable: true });
const options = [{ value: 'a', label: 'First' }, { value: 'b', label: 'Second' }];

describe('dropdown menu stays clear of the system bars', () => {
  it('opening upward never reaches under the status bar', async () => {
    setViewport(400);
    vi.spyOn(HTMLElement.prototype, 'getBoundingClientRect').mockReturnValue(rect(300, 330));   // a field near the bottom of the screen
    render(<Select value="a" onChange={() => {}} options={options} />);
    await userEvent.setup().click(screen.getByRole('button', { name: 'First' }));
    const style = screen.getByRole('listbox').style;
    const menuTop = 400 - parseFloat(style.bottom) - parseFloat(style.maxHeight);
    expect(menuTop).toBeGreaterThanOrEqual(40 + 6);   // status bar (40) + a small gap; without the fix this was 6
  });
  it('opening downward never reaches under the gesture bar', async () => {
    setViewport(400);
    vi.spyOn(HTMLElement.prototype, 'getBoundingClientRect').mockReturnValue(rect(60, 90));   // a field near the top
    render(<Select value="a" onChange={() => {}} options={options} />);
    await userEvent.setup().click(screen.getByRole('button', { name: 'First' }));
    const style = screen.getByRole('listbox').style;
    const menuBottom = parseFloat(style.top) + parseFloat(style.maxHeight);
    expect(menuBottom).toBeLessThanOrEqual(400 - 20 - 6);
  });
});

describe('app pages', () => {
  it('have an opaque strip exactly as tall as the status bar, phones only', () => {
    render(<Shell view="create" setView={() => {}} account={{ email: 'user@example.com', remaining_seconds: 600, daily_minutes: 10, monthly_minutes: 100 }} onLogout={() => {}}><div>Page content</div></Shell>);
    const strip = screen.getByTestId('status-bar-strip');
    expect(strip.style.height).toBe('var(--safe-top)');
    for (const cls of ['fixed', 'top-0', 'inset-x-0', 'bg-page', 'lg:hidden']) expect(strip.className).toContain(cls);
    expect(strip.className).not.toMatch(/bg-page\//);   // opaque: the top bar under it is translucent, so page content would show through
  });
  it('the Create form scrolls into view BELOW the top bar, whatever the status bar height', () => {
    const source = readFileSync(resolve(process.cwd(), 'src/App.jsx'), 'utf8');   // vitest runs from frontend/
    expect(source).toContain('scroll-mt-[calc(max(0.625rem,var(--safe-top))_+_4.5rem)]');   // top bar height (status bar + 56 px) + a gap
    expect(source).not.toMatch(/<form ref=\{formRef\}[^>]*scroll-mt-20/);                   // the old fixed 80 px
  });
});

describe('All voices screen', () => {
  it('keeps the status-bar space inside its opaque sticky header, not as scroll padding', () => {
    const { container } = render(<VoiceLibrary voices={[]} looks={[]} selected="" playing="" onPlay={() => {}} onSelect={() => {}} onClose={() => {}} apiBase="" />);
    const root = container.firstChild;
    expect(root.className).toContain('fixed');
    expect(root.className).not.toContain('pt-[var(--safe-top)]');   // padding of a scroll area lets the list scroll through it, under the clock
    const sticky = container.querySelector('.sticky');
    for (const cls of ['top-0', 'bg-page', 'pt-[max(1rem,var(--safe-top))]']) expect(sticky.className).toContain(cls);
  });
});
