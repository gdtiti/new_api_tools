package service

import (
	"fmt"
	"strings"
	"sync"
	"time"

	"github.com/new-api-tools/backend/internal/database"
	"github.com/new-api-tools/backend/internal/logger"
)

// Activity level constants
const (
	ActivityActive       = "active"
	ActivityInactive     = "inactive"
	ActivityVeryInactive = "very_inactive"
	ActivityNever        = "never"

	ActiveThreshold   = 7 * 24 * 3600  // 7 days
	InactiveThreshold = 30 * 24 * 3600 // 30 days
)

// UserManagementService handles user queries and operations
type UserManagementService struct {
	db    *database.Manager
	logDB *database.Manager
}

// Cached OAuth column existence checks
var (
	oauthColumnsOnce   sync.Once
	availableOAuthCols []string // columns that actually exist in the users table
)

// allOAuthColumns lists all possible OAuth ID columns in New API users table
var allOAuthColumns = []string{"github_id", "wechat_id", "telegram_id", "discord_id", "oidc_id", "linux_do_id"}

// NewUserManagementService creates a new UserManagementService
func NewUserManagementService() *UserManagementService {
	return &UserManagementService{
		db:    database.Get(),
		logDB: database.GetLog(),
	}
}

// getAvailableOAuthColumns returns OAuth columns that exist in the users table (cached)
func (s *UserManagementService) getAvailableOAuthColumns() []string {
	oauthColumnsOnce.Do(func() {
		availableOAuthCols = make([]string, 0)
		for _, col := range allOAuthColumns {
			if s.db.ColumnExists("users", col) {
				availableOAuthCols = append(availableOAuthCols, col)
			}
		}
		logger.L.Business(fmt.Sprintf("检测到 users 表 OAuth 字段: %v", availableOAuthCols))
	})
	return availableOAuthCols
}

// GetActivityStats returns user activity statistics
func (s *UserManagementService) GetActivityStats(quick bool) (map[string]interface{}, error) {
	now := time.Now().Unix()
	activeThreshold := now - ActiveThreshold
	inactiveThreshold := now - InactiveThreshold

	// Total users (not deleted)
	totalRow, err := s.db.QueryOne("SELECT COUNT(*) as count FROM users WHERE deleted_at IS NULL")
	if err != nil {
		return nil, err
	}
	totalUsers := totalRow["count"]

	if quick {
		// Quick mode: only total + never requested
		neverRow, _ := s.db.QueryOne(
			"SELECT COUNT(*) as count FROM users WHERE deleted_at IS NULL AND request_count = 0")
		neverCount := int64(0)
		if neverRow != nil {
			neverCount = toInt64(neverRow["count"])
		}
		return map[string]interface{}{
			"total_users":         totalUsers,
			"active_users":        0,
			"inactive_users":      0,
			"very_inactive_users": 0,
			"never_requested":     neverCount,
			"quick_mode":          true,
		}, nil
	}

	// Full stats: count users by last request time using log DB (no cross-DB join)
	activeUserIDs, err := s.getLogUserIDs(`
		SELECT DISTINCT user_id
		FROM logs
		WHERE user_id IS NOT NULL AND user_id > 0
			AND type IN (2,5) AND created_at >= ?`, activeThreshold)
	if err != nil {
		return nil, err
	}
	activeCount, err := s.countUsersByIDs(activeUserIDs)
	if err != nil {
		return nil, err
	}

	// Inactive: has requests but last request between 7-30 days ago
	inactiveUserIDs, err := s.getLogUserIDs(`
		SELECT DISTINCT user_id
		FROM logs
		WHERE user_id IS NOT NULL AND user_id > 0
			AND type IN (2,5) AND created_at >= ? AND created_at < ?
			AND user_id NOT IN (
				SELECT DISTINCT user_id FROM logs
				WHERE user_id IS NOT NULL AND user_id > 0
					AND type IN (2,5) AND created_at >= ?
			)`, inactiveThreshold, activeThreshold, activeThreshold)
	if err != nil {
		return nil, err
	}
	inactiveCount, err := s.countUsersByIDs(inactiveUserIDs)
	if err != nil {
		return nil, err
	}

	// Never requested
	neverRow, _ := s.db.QueryOne("SELECT COUNT(*) as count FROM users WHERE deleted_at IS NULL AND request_count = 0")
	neverCount := int64(0)
	if neverRow != nil {
		neverCount = toInt64(neverRow["count"])
	}

	total := toInt64(totalUsers)
	veryInactive := total - activeCount - inactiveCount - neverCount

	return map[string]interface{}{
		"total_users":         total,
		"active_users":        activeCount,
		"inactive_users":      inactiveCount,
		"very_inactive_users": veryInactive,
		"never_requested":     neverCount,
	}, nil
}

// ListUsersParams defines parameters for listing users
type ListUsersParams struct {
	Page           int    `json:"page"`
	PageSize       int    `json:"page_size"`
	ActivityFilter string `json:"activity_filter"`
	GroupFilter    string `json:"group_filter"`
	SourceFilter   string `json:"source_filter"`
	Search         string `json:"search"`
	OrderBy        string `json:"order_by"`
	OrderDir       string `json:"order_dir"`
}

// GetUsers returns paginated user list
func (s *UserManagementService) GetUsers(params ListUsersParams) (map[string]interface{}, error) {
	if params.Page < 1 {
		params.Page = 1
	}
	if params.PageSize < 1 || params.PageSize > 100 {
		params.PageSize = 20
	}
	if params.OrderBy == "" {
		params.OrderBy = "request_count"
	}
	if params.OrderDir == "" {
		params.OrderDir = "DESC"
	}

	// Validate order_by
	allowedOrderBy := map[string]bool{
		"id": true, "username": true, "request_count": true,
		"quota": true, "used_quota": true,
	}
	if !allowedOrderBy[params.OrderBy] {
		params.OrderBy = "request_count"
	}
	orderDir := strings.ToUpper(params.OrderDir)
	if orderDir != "ASC" && orderDir != "DESC" {
		orderDir = "DESC"
	}

	groupCol := "`group`"
	if s.db.IsPG {
		groupCol = `"group"`
	}

	// Detect which OAuth columns exist in the database
	oauthCols := s.getAvailableOAuthColumns()
	oauthColSet := make(map[string]bool)
	for _, col := range oauthCols {
		oauthColSet[col] = true
	}

	offset := (params.Page - 1) * params.PageSize
	where := []string{"u.deleted_at IS NULL"}
	args := []interface{}{}
	argIdx := 1

	if params.Search != "" {
		// Build search fields: always include username, display_name, email, aff_code
		// Conditionally include linux_do_id if it exists
		if s.db.IsPG {
			searchFields := []string{
				fmt.Sprintf("u.username ILIKE $%d", argIdx),
				fmt.Sprintf("COALESCE(u.display_name,'') ILIKE $%d", argIdx+1),
				fmt.Sprintf("COALESCE(u.email,'') ILIKE $%d", argIdx+2),
			}
			searchPattern := "%" + params.Search + "%"
			args = append(args, searchPattern, searchPattern, searchPattern)
			nextIdx := argIdx + 3

			if oauthColSet["linux_do_id"] {
				searchFields = append(searchFields, fmt.Sprintf("COALESCE(u.linux_do_id,'') ILIKE $%d", nextIdx))
				args = append(args, searchPattern)
				nextIdx++
			}
			searchFields = append(searchFields, fmt.Sprintf("COALESCE(u.aff_code,'') ILIKE $%d", nextIdx))
			args = append(args, searchPattern)
			nextIdx++

			where = append(where, "("+strings.Join(searchFields, " OR ")+")")
			argIdx = nextIdx
		} else {
			searchFields := []string{
				"u.username LIKE ?",
				"COALESCE(u.display_name,'') LIKE ?",
				"COALESCE(u.email,'') LIKE ?",
			}
			searchPattern := "%" + params.Search + "%"
			args = append(args, searchPattern, searchPattern, searchPattern)

			if oauthColSet["linux_do_id"] {
				searchFields = append(searchFields, "COALESCE(u.linux_do_id,'') LIKE ?")
				args = append(args, searchPattern)
			}
			searchFields = append(searchFields, "COALESCE(u.aff_code,'') LIKE ?")
			args = append(args, searchPattern)

			where = append(where, "("+strings.Join(searchFields, " OR ")+")")
		}
	}
	if params.GroupFilter != "" {
		if s.db.IsPG {
			where = append(where, fmt.Sprintf("u.%s = $%d", groupCol, argIdx))
			argIdx++
		} else {
			where = append(where, fmt.Sprintf("u.%s = ?", groupCol))
		}
		args = append(args, params.GroupFilter)
	}
	if params.ActivityFilter == ActivityNever {
		where = append(where, "u.request_count = 0")
	}

	// Source filter — only apply if the relevant column exists
	if params.SourceFilter != "" {
		var sourceCond string
		switch params.SourceFilter {
		case "password":
			// Password means none of the OAuth columns are set
			condParts := make([]string, 0)
			for _, col := range oauthCols {
				condParts = append(condParts, fmt.Sprintf("(u.%s IS NULL OR u.%s = '')", col, col))
			}
			if len(condParts) > 0 {
				sourceCond = strings.Join(condParts, " AND ")
			}
		default:
			// Map filter name to column name
			colMap := map[string]string{
				"github": "github_id", "wechat": "wechat_id", "telegram": "telegram_id",
				"discord": "discord_id", "oidc": "oidc_id", "linux_do": "linux_do_id",
			}
			if colName, ok := colMap[params.SourceFilter]; ok && oauthColSet[colName] {
				sourceCond = fmt.Sprintf("u.%s IS NOT NULL AND u.%s <> ''", colName, colName)
			}
		}
		if sourceCond != "" {
			where = append(where, "("+sourceCond+")")
		}
	}

	whereClause := strings.Join(where, " AND ")

	// Count total
	countQuery := fmt.Sprintf("SELECT COUNT(*) as count FROM users u WHERE %s", whereClause)
	if !s.db.IsPG {
		countQuery = s.db.RebindQuery(countQuery)
	}
	countRow, err := s.db.QueryOne(countQuery, args...)
	if err != nil {
		return nil, err
	}
	total := toInt64(countRow["count"])

	// Build SELECT columns dynamically based on available OAuth columns
	// NOTE: users table does NOT have created_at — do not select it
	selectCols := fmt.Sprintf("u.id, u.username, u.display_name, u.email, u.role, u.status, u.quota, u.used_quota, u.request_count, u.%s, u.aff_code, u.remark", groupCol)
	for _, col := range oauthCols {
		selectCols += fmt.Sprintf(", u.%s", col)
	}

	var selectQuery string
	if s.db.IsPG {
		selectQuery = fmt.Sprintf(
			"SELECT %s FROM users u WHERE %s ORDER BY u.%s %s LIMIT $%d OFFSET $%d",
			selectCols, whereClause, params.OrderBy, orderDir, argIdx, argIdx+1)
		args = append(args, params.PageSize, offset)
	} else {
		selectQuery = fmt.Sprintf(
			"SELECT %s FROM users u WHERE %s ORDER BY u.%s %s LIMIT ? OFFSET ?",
			selectCols, whereClause, params.OrderBy, orderDir)
		args = append(args, params.PageSize, offset)
		selectQuery = s.db.RebindQuery(selectQuery)
	}

	rows, err := s.db.Query(selectQuery, args...)
	if err != nil {
		logger.L.Error(fmt.Sprintf("GetUsers 查询失败: %v, SQL: %s, args: %v", err, selectQuery, args))
		return nil, err
	}
	if rows == nil {
		rows = []map[string]interface{}{}
	}

	// Enrich rows with computed fields (activity_level, source, linux_do_id)
	for _, row := range rows {
		reqCount := toInt64(row["request_count"])
		if reqCount == 0 {
			row["activity_level"] = ActivityNever
		} else {
			row["activity_level"] = ActivityActive
		}
		row["last_request_time"] = nil

		// Preserve linux_do_id for frontend display
		linuxDoID := ""
		if oauthColSet["linux_do_id"] {
			linuxDoID = toString(row["linux_do_id"])
		}
		row["linux_do_id"] = linuxDoID

		// Compute source from OAuth ID fields (only check existing columns)
		source := "password"
		if oauthColSet["linux_do_id"] && toString(row["linux_do_id"]) != "" {
			source = "linux_do"
		} else if oauthColSet["github_id"] && toString(row["github_id"]) != "" {
			source = "github"
		} else if oauthColSet["wechat_id"] && toString(row["wechat_id"]) != "" {
			source = "wechat"
		} else if oauthColSet["telegram_id"] && toString(row["telegram_id"]) != "" {
			source = "telegram"
		} else if oauthColSet["discord_id"] && toString(row["discord_id"]) != "" {
			source = "discord"
		} else if oauthColSet["oidc_id"] && toString(row["oidc_id"]) != "" {
			source = "oidc"
		}
		row["source"] = source

		// Clean up internal OAuth fields (except linux_do_id which is kept)
		for _, col := range oauthCols {
			if col != "linux_do_id" {
				delete(row, col)
			}
		}
	}

	totalPages := int((total + int64(params.PageSize) - 1) / int64(params.PageSize))

	return map[string]interface{}{
		"items":       rows,
		"total":       total,
		"page":        params.Page,
		"page_size":   params.PageSize,
		"total_pages": totalPages,
	}, nil
}

// GetBannedUsers returns banned users list
func (s *UserManagementService) GetBannedUsers(page, pageSize int, search string) (map[string]interface{}, error) {
	if page < 1 {
		page = 1
	}
	if pageSize < 1 || pageSize > 100 {
		pageSize = 50
	}

	offset := (page - 1) * pageSize
	where := "u.status = 2 AND u.deleted_at IS NULL"
	args := []interface{}{}

	if search != "" {
		if s.db.IsPG {
			where += " AND u.username ILIKE $1"
		} else {
			where += " AND u.username LIKE ?"
		}
		args = append(args, "%"+search+"%")
	}

	// Count
	countQuery := s.db.RebindQuery(fmt.Sprintf("SELECT COUNT(*) as count FROM users u WHERE %s", where))
	countRow, _ := s.db.QueryOne(countQuery, args...)
	total := int64(0)
	if countRow != nil {
		total = toInt64(countRow["count"])
	}

	// Query
	query := fmt.Sprintf(
		"SELECT u.id, u.username, u.display_name, u.email, u.status, u.role, "+
			"u.quota, u.used_quota, u.request_count "+
			"FROM users u WHERE %s ORDER BY u.id DESC LIMIT %d OFFSET %d",
		where, pageSize, offset)
	if !s.db.IsPG {
		query = s.db.RebindQuery(query)
	}

	rows, err := s.db.Query(query, args...)
	if err != nil {
		return nil, err
	}

	totalPages := int((total + int64(pageSize) - 1) / int64(pageSize))

	return map[string]interface{}{
		"items":       rows,
		"total":       total,
		"page":        page,
		"page_size":   pageSize,
		"total_pages": totalPages,
	}, nil
}

// DeleteUser soft-deletes a user
func (s *UserManagementService) DeleteUser(userID int64, hardDelete bool) (int64, error) {
	if hardDelete {
		// Hard delete: remove user and associated data
		s.db.Execute(s.db.RebindQuery("DELETE FROM tokens WHERE user_id = ?"), userID)
		affected, err := s.db.Execute(s.db.RebindQuery("DELETE FROM users WHERE id = ?"), userID)
		if err != nil {
			return 0, err
		}
		logger.L.Business(fmt.Sprintf("用户 %d 已彻底删除", userID))
		return affected, nil
	}

	// Soft delete
	now := time.Now().Unix()
	affected, err := s.db.Execute(s.db.RebindQuery(
		"UPDATE users SET deleted_at = ? WHERE id = ? AND deleted_at IS NULL"), now, userID)
	if err != nil {
		return 0, err
	}
	if affected > 0 {
		logger.L.Business(fmt.Sprintf("用户 %d 已注销", userID))
	}
	return affected, nil
}

// BanUser sets user status to banned (2)
func (s *UserManagementService) BanUser(userID int64, disableTokens bool) error {
	_, err := s.db.Execute(s.db.RebindQuery("UPDATE users SET status = 2 WHERE id = ?"), userID)
	if err != nil {
		return err
	}
	if disableTokens {
		s.db.Execute(s.db.RebindQuery("UPDATE tokens SET status = 2 WHERE user_id = ?"), userID)
	}
	logger.L.Security(fmt.Sprintf("用户 %d 已封禁", userID))
	return nil
}

// UnbanUser sets user status to active (1)
func (s *UserManagementService) UnbanUser(userID int64, enableTokens bool) error {
	_, err := s.db.Execute(s.db.RebindQuery("UPDATE users SET status = 1 WHERE id = ?"), userID)
	if err != nil {
		return err
	}
	if enableTokens {
		s.db.Execute(s.db.RebindQuery("UPDATE tokens SET status = 1 WHERE user_id = ?"), userID)
	}
	logger.L.Security(fmt.Sprintf("用户 %d 已解封", userID))
	return nil
}

// DisableToken disables a single token
func (s *UserManagementService) DisableToken(tokenID int64) error {
	_, err := s.db.Execute(s.db.RebindQuery("UPDATE tokens SET status = 2 WHERE id = ?"), tokenID)
	if err != nil {
		return err
	}
	logger.L.Security(fmt.Sprintf("Token %d 已禁用", tokenID))
	return nil
}

// GetSoftDeletedCount returns count of soft-deleted users
func (s *UserManagementService) GetSoftDeletedCount() (int64, error) {
	row, err := s.db.QueryOne("SELECT COUNT(*) as count FROM users WHERE deleted_at IS NOT NULL")
	if err != nil {
		return 0, err
	}
	return toInt64(row["count"]), nil
}

// PurgeSoftDeleted permanently deletes soft-deleted users
func (s *UserManagementService) PurgeSoftDeleted(dryRun bool) (int64, error) {
	if dryRun {
		return s.GetSoftDeletedCount()
	}

	// Delete associated tokens first
	s.db.Execute("DELETE FROM tokens WHERE user_id IN (SELECT id FROM users WHERE deleted_at IS NOT NULL)")

	affected, err := s.db.Execute("DELETE FROM users WHERE deleted_at IS NOT NULL")
	if err != nil {
		return 0, err
	}
	logger.L.Business(fmt.Sprintf("已清理 %d 个软删除用户", affected))
	return affected, nil
}

// BatchDeleteInactiveUsers deletes inactive users
func (s *UserManagementService) BatchDeleteInactiveUsers(activityLevel string, dryRun, hardDelete bool) (map[string]interface{}, error) {
	now := time.Now().Unix()
	var condition string

	switch activityLevel {
	case ActivityNever:
		condition = "request_count = 0"
	case ActivityVeryInactive:
		threshold := now - InactiveThreshold
		userIDs, err := s.getInactiveUserIDsByLogThreshold(threshold)
		if err != nil {
			return nil, err
		}
		affected := int64(len(userIDs))
		if dryRun {
			return map[string]interface{}{
				"dry_run":        true,
				"affected_count": affected,
				"activity_level": activityLevel,
			}, nil
		}
		if err := s.applyBatchUserDelete(userIDs, hardDelete, now); err != nil {
			return nil, err
		}
		logger.L.Business(fmt.Sprintf("批量删除 %s 用户: %d 个", activityLevel, affected))
		return map[string]interface{}{
			"dry_run":        false,
			"affected_count": affected,
			"activity_level": activityLevel,
			"hard_delete":    hardDelete,
		}, nil
	case ActivityInactive:
		threshold := now - ActiveThreshold
		userIDs, err := s.getInactiveUserIDsByLogThreshold(threshold)
		if err != nil {
			return nil, err
		}
		affected := int64(len(userIDs))
		if dryRun {
			return map[string]interface{}{
				"dry_run":        true,
				"affected_count": affected,
				"activity_level": activityLevel,
			}, nil
		}
		if err := s.applyBatchUserDelete(userIDs, hardDelete, now); err != nil {
			return nil, err
		}
		logger.L.Business(fmt.Sprintf("批量删除 %s 用户: %d 个", activityLevel, affected))
		return map[string]interface{}{
			"dry_run":        false,
			"affected_count": affected,
			"activity_level": activityLevel,
			"hard_delete":    hardDelete,
		}, nil
	default:
		return nil, fmt.Errorf("invalid activity level: %s", activityLevel)
	}

	// Count affected users
	countRow, err := s.db.QueryOne(fmt.Sprintf(
		"SELECT COUNT(*) as count FROM users WHERE deleted_at IS NULL AND role != 100 AND %s", condition))
	if err != nil {
		return nil, err
	}
	affected := toInt64(countRow["count"])

	if dryRun {
		return map[string]interface{}{
			"dry_run":        true,
			"affected_count": affected,
			"activity_level": activityLevel,
		}, nil
	}

	// Execute delete
	if hardDelete {
		s.db.Execute(fmt.Sprintf(
			"DELETE FROM tokens WHERE user_id IN (SELECT id FROM users WHERE deleted_at IS NULL AND role != 100 AND %s)", condition))
		s.db.Execute(fmt.Sprintf(
			"DELETE FROM users WHERE deleted_at IS NULL AND role != 100 AND %s", condition))
	} else {
		s.db.Execute(fmt.Sprintf(
			"UPDATE users SET deleted_at = %d WHERE deleted_at IS NULL AND role != 100 AND %s", now, condition))
	}

	logger.L.Business(fmt.Sprintf("批量删除 %s 用户: %d 个", activityLevel, affected))

	return map[string]interface{}{
		"dry_run":        false,
		"affected_count": affected,
		"activity_level": activityLevel,
		"hard_delete":    hardDelete,
	}, nil
}

func (s *UserManagementService) getLogUserIDs(query string, args ...interface{}) ([]int64, error) {
	query = s.logDB.RebindQuery(query)
	rows, err := s.logDB.Query(query, args...)
	if err != nil || rows == nil {
		return nil, err
	}
	result := make([]int64, 0, len(rows))
	seen := make(map[int64]struct{})
	for _, row := range rows {
		userID := toInt64(row["user_id"])
		if userID <= 0 {
			continue
		}
		if _, ok := seen[userID]; ok {
			continue
		}
		seen[userID] = struct{}{}
		result = append(result, userID)
	}
	return result, nil
}

func (s *UserManagementService) countUsersByIDs(userIDs []int64) (int64, error) {
	if len(userIDs) == 0 {
		return 0, nil
	}
	const batchSize = 500
	var total int64
	for i := 0; i < len(userIDs); i += batchSize {
		end := i + batchSize
		if end > len(userIDs) {
			end = len(userIDs)
		}
		batch := userIDs[i:end]
		placeholders := buildPlaceholders(s.db.IsPG, len(batch), 1)
		query := fmt.Sprintf("SELECT COUNT(*) as count FROM users WHERE deleted_at IS NULL AND request_count > 0 AND id IN (%s)", placeholders)
		if !s.db.IsPG {
			query = s.db.RebindQuery(query)
		}
		args := make([]interface{}, 0, len(batch))
		for _, id := range batch {
			args = append(args, id)
		}
		row, err := s.db.QueryOne(query, args...)
		if err != nil {
			return 0, err
		}
		if row != nil {
			total += toInt64(row["count"])
		}
	}
	return total, nil
}

func (s *UserManagementService) getInactiveUserIDsByLogThreshold(threshold int64) ([]int64, error) {
	recentIDs, err := s.getLogUserIDs(`
		SELECT DISTINCT user_id
		FROM logs
		WHERE user_id IS NOT NULL AND user_id > 0
			AND type IN (2,5) AND created_at >= ?`, threshold)
	if err != nil {
		return nil, err
	}
	recentSet := make(map[int64]struct{}, len(recentIDs))
	for _, id := range recentIDs {
		recentSet[id] = struct{}{}
	}
	rows, err := s.db.Query("SELECT id FROM users WHERE deleted_at IS NULL AND role != 100 AND request_count > 0")
	if err != nil {
		return nil, err
	}
	target := make([]int64, 0, len(rows))
	for _, row := range rows {
		id := toInt64(row["id"])
		if id <= 0 {
			continue
		}
		if _, ok := recentSet[id]; ok {
			continue
		}
		target = append(target, id)
	}
	return target, nil
}

func (s *UserManagementService) applyBatchUserDelete(userIDs []int64, hardDelete bool, deletedAt int64) error {
	if len(userIDs) == 0 {
		return nil
	}
	const batchSize = 500
	for i := 0; i < len(userIDs); i += batchSize {
		end := i + batchSize
		if end > len(userIDs) {
			end = len(userIDs)
		}
		batch := userIDs[i:end]
		placeholders := buildPlaceholders(s.db.IsPG, len(batch), 1)
		args := make([]interface{}, 0, len(batch))
		for _, id := range batch {
			args = append(args, id)
		}
		if hardDelete {
			tokenQuery := fmt.Sprintf("DELETE FROM tokens WHERE user_id IN (%s)", placeholders)
			userQuery := fmt.Sprintf("DELETE FROM users WHERE id IN (%s)", placeholders)
			if !s.db.IsPG {
				tokenQuery = s.db.RebindQuery(tokenQuery)
				userQuery = s.db.RebindQuery(userQuery)
			}
			if _, err := s.db.Execute(tokenQuery, args...); err != nil {
				return err
			}
			if _, err := s.db.Execute(userQuery, args...); err != nil {
				return err
			}
		} else {
			var updateQuery string
			var updateArgs []interface{}
			if s.db.IsPG {
				updateQuery = fmt.Sprintf("UPDATE users SET deleted_at = $1 WHERE id IN (%s)", buildPlaceholders(true, len(batch), 2))
				updateArgs = append(updateArgs, deletedAt)
			} else {
				updateQuery = fmt.Sprintf("UPDATE users SET deleted_at = ? WHERE id IN (%s)", placeholders)
				updateQuery = s.db.RebindQuery(updateQuery)
				updateArgs = append(updateArgs, deletedAt)
			}
			for _, id := range batch {
				updateArgs = append(updateArgs, id)
			}
			if _, err := s.db.Execute(updateQuery, updateArgs...); err != nil {
				return err
			}
		}
	}
	return nil
}

// toInt64 safely converts interface{} to int64
func toInt64(v interface{}) int64 {
	if v == nil {
		return 0
	}
	switch val := v.(type) {
	case int64:
		return val
	case int:
		return int64(val)
	case int32:
		return int64(val)
	case float64:
		return int64(val)
	case float32:
		return int64(val)
	case string:
		var n int64
		fmt.Sscanf(val, "%d", &n)
		return n
	case []byte:
		var n int64
		fmt.Sscanf(string(val), "%d", &n)
		return n
	default:
		return 0
	}
}

// toString safely converts interface{} to string
func toString(v interface{}) string {
	if v == nil {
		return ""
	}
	switch val := v.(type) {
	case string:
		return val
	case []byte:
		return string(val)
	default:
		return fmt.Sprintf("%v", val)
	}
}

// GetInvitedUsers returns users invited by the specified user
func (s *UserManagementService) GetInvitedUsers(userID int64, page, pageSize int) (map[string]interface{}, error) {
	offset := (page - 1) * pageSize

	// Get inviter info
	inviterRow, err := s.db.QueryOne(s.db.RebindQuery(
		"SELECT id, username, display_name, aff_code, aff_count, aff_quota, aff_history FROM users WHERE id = ? AND deleted_at IS NULL"), userID)
	if err != nil || inviterRow == nil {
		return map[string]interface{}{
			"inviter":   nil,
			"items":     []interface{}{},
			"total":     0,
			"page":      page,
			"page_size": pageSize,
			"stats":     map[string]interface{}{},
		}, nil
	}

	inviter := map[string]interface{}{
		"user_id":      inviterRow["id"],
		"username":     inviterRow["username"],
		"display_name": inviterRow["display_name"],
		"aff_code":     inviterRow["aff_code"],
		"aff_count":    inviterRow["aff_count"],
		"aff_quota":    inviterRow["aff_quota"],
		"aff_history":  inviterRow["aff_history"],
	}

	// Count total invited
	countRow, _ := s.db.QueryOne(s.db.RebindQuery(
		"SELECT COUNT(*) as total FROM users WHERE inviter_id = ? AND deleted_at IS NULL"), userID)
	total := int64(0)
	if countRow != nil {
		total = toInt64(countRow["total"])
	}

	// Get invited users list
	groupCol := "`group`"
	if s.db.IsPG {
		groupCol = `"group"`
	}
	query := s.db.RebindQuery(fmt.Sprintf(`
		SELECT id, username, display_name, email, status,
			quota, used_quota, request_count, %s, role
		FROM users
		WHERE inviter_id = ? AND deleted_at IS NULL
		ORDER BY id DESC
		LIMIT ? OFFSET ?`,
		groupCol))

	rows, err := s.db.Query(query, userID, pageSize, offset)
	if err != nil {
		return nil, err
	}

	// Compute stats
	activeCount := 0
	bannedCount := 0
	totalUsedQuota := int64(0)
	totalRequests := int64(0)
	for _, row := range rows {
		if toInt64(row["request_count"]) > 0 {
			activeCount++
		}
		if toInt64(row["status"]) == 2 {
			bannedCount++
		}
		totalUsedQuota += toInt64(row["used_quota"])
		totalRequests += toInt64(row["request_count"])
	}

	return map[string]interface{}{
		"inviter":   inviter,
		"items":     rows,
		"total":     total,
		"page":      page,
		"page_size": pageSize,
		"stats": map[string]interface{}{
			"total_invited":    total,
			"active_count":     activeCount,
			"banned_count":     bannedCount,
			"total_used_quota": totalUsedQuota,
			"total_requests":   totalRequests,
		},
	}, nil
}
