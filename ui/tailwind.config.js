import { addDynamicIconSelectors } from '@iconify/tailwind'
import flyonui from 'flyonui'

/** @type {import('tailwindcss').Config} */
export default {
  content: [
    './index.html',
    './src/**/*.{svelte,js,ts}',
    './node_modules/flyonui/dist/js/*.js'
  ],
  theme: {
    extend: {
      fontFamily: {
        mono: ["'Berkeley Mono'", "'SF Mono'", 'Monaco', 'Inconsolata', "'Roboto Mono'", 'monospace'],
        sans: ["'Inter'", "'SF Pro Display'", 'system-ui', 'sans-serif']
      },
      fontSize: {
        'xs': ['11px', '16px'],
        'sm': ['12px', '18px'],
        'base': ['13px', '20px'],
        'lg': ['14px', '22px'],
        'xl': ['16px', '24px']
      },
      colors: {
        'va-canvas': '#121417',
        'va-subtle': '#1c1f24',
        'va-border': '#2e3339',
        'va-hover': '#252a30',
        'va-active': '#2e3339',
        'va-text': '#c5c9ce',
        'va-muted': '#7d8590',
        'va-accent': '#6b9eff',
        'va-success': '#57ab5a',
        'va-danger': '#e5534b',
        'va-warning': '#c69026',
        slate: {
          950: '#121417',
          900: '#1c1f24',
          800: '#252a30',
          700: '#2e3339',
          600: '#3d444d',
          500: '#545d68',
          400: '#7d8590',
          300: '#9ca3af',
          200: '#c5c9ce',
          100: '#e6e8eb'
        }
      },
      boxShadow: {
        'soft': '0 2px 8px rgba(0, 0, 0, 0.2)',
        'medium': '0 4px 16px rgba(0, 0, 0, 0.3)',
        'glow': '0 0 20px rgba(107, 158, 255, 0.1)'
      }
    }
  },
  flyonui: {
    themes: [
      {
        vibe: {
          'primary': '#6b9eff',
          'secondary': '#7d8590',
          'accent': '#6b9eff',
          'neutral': '#1c1f24',
          'base-100': '#121417',
          'base-200': '#1c1f24',
          'base-300': '#252a30',
          'base-content': '#c5c9ce',
          'info': '#6b9eff',
          'success': '#57ab5a',
          'warning': '#c69026',
          'error': '#e5534b',
          '--rounded-box': '12px',
          '--rounded-btn': '10px',
          '--rounded-field': '10px',
        }
      }
    ]
  },
  plugins: [flyonui, addDynamicIconSelectors()]
}
