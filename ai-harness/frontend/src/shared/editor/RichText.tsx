// WYSIWYG-редактор описания на TipTap: форматирование к выделению, заголовки 1–5
// выпадающим списком, списки, цитата, ссылка, изображение, код, таблица (ФТ-ah-5, §14).

import Image from '@tiptap/extension-image'
import Link from '@tiptap/extension-link'
import Table from '@tiptap/extension-table'
import TableCell from '@tiptap/extension-table-cell'
import TableHeader from '@tiptap/extension-table-header'
import TableRow from '@tiptap/extension-table-row'
import Underline from '@tiptap/extension-underline'
import { EditorContent, useEditor } from '@tiptap/react'
import StarterKit from '@tiptap/starter-kit'
import { useEffect, useRef, useState } from 'react'
import { renderMarkdown } from '../markdown'
import { htmlToMarkdown } from './serialize'

export interface RichTextProps {
  markdown: string
  onChange: (markdown: string) => void
}

export function RichText({ markdown, onChange }: RichTextProps) {
  // редактирование не должно терять каретку: контент из пропа ставится только
  // когда он пришёл извне (а не из нашего же onUpdate)
  const lastEmitted = useRef(markdown)
  const [inTable, setInTable] = useState(false)
  const editor = useEditor({
    extensions: [
      StarterKit, Underline, Link, Image,
      Table.configure({ resizable: false }), TableRow, TableHeader, TableCell,
    ],
    content: renderMarkdown(markdown),
    onUpdate: ({ editor }) => {
      const md = htmlToMarkdown(editor.getHTML())
      lastEmitted.current = md
      onChange(md)
    },
  })

  useEffect(() => {
    if (editor && markdown !== lastEmitted.current) {
      editor.commands.setContent(renderMarkdown(markdown))
      lastEmitted.current = markdown
    }
  }, [markdown]) // eslint-disable-line react-hooks/exhaustive-deps

  // табличные операции контекстны: панель появляется, когда курсор в таблице
  useEffect(() => {
    if (!editor) return
    const upd = () => setInTable(editor.isActive('table'))
    editor.on('selectionUpdate', upd)
    editor.on('transaction', upd)
    return () => {
      editor.off('selectionUpdate', upd)
      editor.off('transaction', upd)
    }
  }, [editor])

  if (!editor) return null
  const cmd = (fn: () => void) => () => { fn(); editor.view.focus() }

  return (
    <div className="rich-wrap">
      <div className="editbar">
        <button onClick={cmd(() => editor.chain().focus().toggleBold().run())}><b>Ж</b></button>
        <button onClick={cmd(() => editor.chain().focus().toggleItalic().run())}><i>К</i></button>
        <button onClick={cmd(() => editor.chain().focus().toggleUnderline().run())}><u>П</u></button>
        <button onClick={cmd(() => editor.chain().focus().toggleStrike().run())}><s>З</s></button>
        <select onChange={(e) => {
          const level = Number(e.target.value)
          if (level === 0) editor.chain().focus().setParagraph().run()
          else editor.chain().focus().toggleHeading({ level: level as 1 | 2 | 3 | 4 | 5 }).run()
        }} value={''} aria-label="Уровень заголовка">
          <option value="" disabled>Заголовок…</option>
          <option value="0">Обычный текст</option>
          {[1, 2, 3, 4, 5].map((l) => <option key={l} value={l}>Заголовок {l}</option>)}
        </select>
        <button onClick={cmd(() => editor.chain().focus().toggleBulletList().run())}>•—</button>
        <button onClick={cmd(() => editor.chain().focus().toggleOrderedList().run())}>1.</button>
        <button onClick={cmd(() => editor.chain().focus().toggleBlockquote().run())}>❝</button>
        <button onClick={cmd(() => editor.chain().focus().toggleCodeBlock().run())}>{ }</button>
        <button onClick={cmd(() => {
          const url = window.prompt('Адрес ссылки')
          if (url) editor.chain().focus().setLink({ href: url }).run()
        })}>🔗</button>
        <button onClick={cmd(() => {
          const src = window.prompt('Источник изображения')
          if (src) editor.chain().focus().setImage({ src }).run()
        })}>🖼</button>
        <button onClick={cmd(() => editor.chain().focus().insertTable({ rows: 2, cols: 2, withHeaderRow: true }).run())}
          title="Вставить таблицу">⊞</button>
      </div>
      {inTable && (
        <div className="table-bar">
          <span>Таблица:</span>
          <button onClick={cmd(() => editor.chain().focus().addRowAfter().run())}>＋ строка</button>
          <button onClick={cmd(() => editor.chain().focus().deleteRow().run())}>− строка</button>
          <button onClick={cmd(() => editor.chain().focus().addColumnAfter().run())}>＋ столбец</button>
          <button onClick={cmd(() => editor.chain().focus().deleteColumn().run())}>− столбец</button>
          <button className="danger" onClick={cmd(() => editor.chain().focus().deleteTable().run())}>удалить таблицу</button>
        </div>
      )}
      <div className="rich-edit"><EditorContent editor={editor} /></div>
    </div>
  )
}
