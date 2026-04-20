# AGENTS.md

Guidance for agents working in this repository.

## Core Rule

This repo is mainly maintained by editing navigation config, not by changing application code.

<IMPORTANT>
Unless the user explicitly asks for a code fix or feature, only edit:

- `src/mock/mock_data.js`
- `download_ico.py`

Do not modify Vue components, styles, router, deployment files, or backend files for normal site/category updates.
</IMPORTANT>

If you need to edit other files, ask for permission first.

## Main File

`src/mock/mock_data.js` is the source of truth for navigation data.

When the user asks to:

- add a website
- remove a website
- move a website
- rename a category
- create or merge categories
- update descriptions

edit `src/mock/mock_data.js`.

## Data Rules

Keep the existing structure:

```js
export const mockData = {
  categories: [
    {
      id: "category-id",
      name: "分类名",
      icon: "💥",
      order: 0,
      sites: [
        {
          id: "site-id",
          name: "Site Name",
          url: "https://example.com",
          description: "short description",
          icon: "/sitelogo/example.com.ico"
        }
      ]
    }
  ]
}
```

Use these rules when editing:

- Prefer existing categories first.
- Only create a new category when the user asks for it or when the current category is clearly too mixed.
- Keep category names short and clear.
- Keep site descriptions short.
- Use lowercase kebab-case `id` values when practical.
- Keep `order` values stable and sensible.
- Preserve the current file style and formatting.

## Icon Rules

- The icon path should normally be `/sitelogo/<host>.ico`.
- Do not worry whether the icon file already exists.
- Missing icons can be fetched later by `download_ico.py`.
- To download missing icons, run: `./download_ico.py`.
- Do not block a config change just because the icon has not been downloaded yet.

## Scope Control

For normal navigation maintenance, do not "clean up" unrelated entries.

Do not:

- refactor the file structure
- rename unrelated ids
- reorder large sections without being asked
- edit source code just because it looks improvable

If a request really requires app code changes, stop and ask before changing files outside `src/mock/mock_data.js`.
