/**
 * PyRunner UI theme — light/dark via CSS variables (class on <html>)
 */

module.exports = {
    content: [
        '../templates/**/*.html',
        '../../templates/**/*.html',
        '../../**/templates/**/*.html',
    ],
    darkMode: 'class',
    theme: {
        extend: {
            fontFamily: {
                sans: [
                    'Inter',
                    'ui-sans-serif',
                    'system-ui',
                    '-apple-system',
                    'Segoe UI',
                    'Roboto',
                    'Helvetica Neue',
                    'Arial',
                    'sans-serif',
                ],
            },
            boxShadow: {
                card: 'var(--shadow-card)',
                'card-hover': 'var(--shadow-card-hover)',
            },
            colors: {
                'code-bg': 'rgb(var(--color-bg) / <alpha-value>)',
                'code-surface': 'rgb(var(--color-surface) / <alpha-value>)',
                'code-border': 'rgb(var(--color-border) / <alpha-value>)',
                'code-text': 'rgb(var(--color-text) / <alpha-value>)',
                'code-muted': 'rgb(var(--color-muted) / <alpha-value>)',
                'code-accent': 'rgb(var(--color-accent) / <alpha-value>)',
                'code-accent-fg': 'rgb(var(--color-accent-fg) / <alpha-value>)',
                'code-nav-hover': 'rgb(var(--color-nav-hover) / <alpha-value>)',
                'code-nav-active': 'rgb(var(--color-nav-active) / <alpha-value>)',
                'code-link': 'rgb(var(--color-link) / <alpha-value>)',
                'code-green': 'rgb(var(--color-green) / <alpha-value>)',
                'code-yellow': 'rgb(var(--color-yellow) / <alpha-value>)',
                'code-red': 'rgb(var(--color-red) / <alpha-value>)',
                'code-purple': 'rgb(var(--color-purple) / <alpha-value>)',
            },
        },
    },
    plugins: [
        require('@tailwindcss/forms'),
        require('@tailwindcss/typography'),
        require('@tailwindcss/aspect-ratio'),
    ],
}
