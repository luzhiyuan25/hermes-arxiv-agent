const state = {
  papers: [],
  newIds: new Set(),
  favorites: new Set(JSON.parse(localStorage.getItem("daily-papers:favorites") || "[]")),
  meta: null,
};

const $ = (id) => document.getElementById(id);

function saveFavorites() {
  localStorage.setItem("daily-papers:favorites", JSON.stringify([...state.favorites]));
}

function normalize(value) {
  return String(value || "");
}

function categoriesOf(paper) {
  return normalize(paper.categories)
    .split(",")
    .map((item) => item.trim())
    .filter(Boolean);
}

function within(value, start, end) {
  if (!value) return false;
  if (start && value < start) return false;
  if (end && value > end) return false;
  return true;
}

function matchesKeyword(paper, keyword) {
  if (!keyword) return true;
  const haystack = [
    paper.arxiv_id,
    paper.title,
    paper.authors,
    paper.categories,
    paper.abstract,
    paper.summary_cn,
    paper.affiliations,
  ].join(" ").toLowerCase();
  return haystack.includes(keyword.toLowerCase());
}

function renderCategories() {
  const select = $("category");
  const selected = select.value;
  const categories = [...new Set(state.papers.flatMap(categoriesOf))].sort();
  select.innerHTML = '<option value="">全部</option>';
  for (const category of categories) {
    const option = document.createElement("option");
    option.value = category;
    option.textContent = category;
    select.appendChild(option);
  }
  select.value = categories.includes(selected) ? selected : "";
}

function renderPapers(papers) {
  const container = $("papers");
  const template = $("paperTemplate");
  container.textContent = "";

  if (!papers.length) {
    const empty = document.createElement("p");
    empty.className = "empty";
    empty.textContent = "没有匹配的论文。";
    container.appendChild(empty);
    return;
  }

  for (const paper of papers) {
    const node = template.content.cloneNode(true);
    const article = node.querySelector(".paper");
    const arxivId = normalize(paper.arxiv_id);
    const isNew = state.newIds.has(arxivId);
    article.classList.toggle("is-new", isNew);

    node.querySelector(".id").textContent = `${arxivId}${isNew ? " / NEW" : ""}`;
    const fav = node.querySelector(".favorite");
    fav.textContent = state.favorites.has(arxivId) ? "★" : "☆";
    fav.classList.toggle("active", state.favorites.has(arxivId));
    fav.addEventListener("click", () => {
      if (state.favorites.has(arxivId)) {
        state.favorites.delete(arxivId);
      } else {
        state.favorites.add(arxivId);
      }
      saveFavorites();
      applyFilters();
    });

    const title = node.querySelector(".title");
    title.textContent = normalize(paper.title) || arxivId;
    title.href = paper.abs_url || `https://arxiv.org/abs/${arxivId}`;
    node.querySelector(".authors").textContent = [
      normalize(paper.published_date),
      normalize(paper.authors),
    ].filter(Boolean).join(" | ");

    const tags = node.querySelector(".tags");
    for (const category of categoriesOf(paper)) {
      const tag = document.createElement("span");
      tag.textContent = category;
      tags.appendChild(tag);
    }

    node.querySelector(".abstract").textContent = normalize(paper.summary_cn || paper.abstract);
    node.querySelector(".abs").href = paper.abs_url || `https://arxiv.org/abs/${arxivId}`;
    node.querySelector(".pdf").href = paper.pdf_url || `https://arxiv.org/pdf/${arxivId}`;
    container.appendChild(node);
  }
}

function applyFilters() {
  const dateMode = $("dateMode").value;
  const start = $("startDate").value;
  const end = $("endDate").value;
  const keyword = $("keyword").value.trim();
  const category = $("category").value;
  const newOnly = $("newOnly").checked;
  const favoriteOnly = $("favoriteOnly").checked;

  const filtered = state.papers.filter((paper) => {
    const arxivId = normalize(paper.arxiv_id);
    return (
      within(normalize(paper[dateMode]), start, end) &&
      matchesKeyword(paper, keyword) &&
      (!category || categoriesOf(paper).includes(category)) &&
      (!newOnly || state.newIds.has(arxivId)) &&
      (!favoriteOnly || state.favorites.has(arxivId))
    );
  });

  $("stats").textContent =
    `总计 ${state.papers.length} 篇，今日新增 ${state.newIds.size} 篇，当前展示 ${filtered.length} 篇，收藏 ${state.favorites.size} 篇`;
  renderPapers(filtered);
}

function resetFilters() {
  $("dateMode").value = "published_date";
  $("startDate").value = state.meta?.published_date_min || "";
  $("endDate").value = state.meta?.published_date_max || "";
  $("keyword").value = "";
  $("category").value = "";
  $("newOnly").checked = false;
  $("favoriteOnly").checked = false;
  applyFilters();
}

async function init() {
  const res = await fetch("papers_data.json", { cache: "no-store" });
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  state.meta = await res.json();
  state.papers = state.meta.papers || [];
  state.newIds = new Set((state.meta.new_papers || []).map((paper) => normalize(paper.arxiv_id)));

  $("metaText").textContent =
    `更新于 ${state.meta.generated_at || "-"}，收录 ${state.meta.count || state.papers.length} 篇`;
  renderCategories();
  resetFilters();

  $("applyBtn").addEventListener("click", applyFilters);
  $("resetBtn").addEventListener("click", resetFilters);
  $("keyword").addEventListener("keydown", (event) => {
    if (event.key === "Enter") applyFilters();
  });
  $("category").addEventListener("change", applyFilters);
  $("newOnly").addEventListener("change", applyFilters);
  $("favoriteOnly").addEventListener("change", applyFilters);
}

init().catch((error) => {
  $("stats").textContent = `加载失败：${error.message}`;
});
