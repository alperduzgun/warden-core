; Kotlin tree-sitter queries for Spring Boot API contract extraction
; Used by SpringBootExtractor for precise AST-based extraction

; ============================================
; Controller Annotations
; ============================================

; @RestController
(annotation
  (user_type
    (type_identifier) @annotation_name
    (#match? @annotation_name "^(RestController|Controller)$")
  )
) @controller_annotation

; @GetMapping("/users")
(annotation
  (user_type
    (type_identifier) @mapping_name
    (#match? @mapping_name "^(RequestMapping|GetMapping|PostMapping|PutMapping|PatchMapping|DeleteMapping)$")
  )
  (value_arguments
    (value_argument
      (string_literal) @path_value
    )?
  )?
) @mapping_annotation

; ============================================
; Controller Class
; ============================================

; class UsersController
(class_declaration
  (modifiers
    (annotation)* @class_annotations
  )?
  name: (type_identifier) @class_name
  body: (class_body)? @class_body
) @controller_class

; ============================================
; Handler Functions
; ============================================

; fun getUsers(): List<User>
; suspend fun getUsers(): List<User>
(function_declaration
  (modifiers
    (annotation)* @func_annotations
    (modifier)? @suspend_modifier
  )?
  name: (simple_identifier) @func_name
  parameters: (function_value_parameters) @params
  returnType: (user_type)? @return_type
  body: (function_body)? @func_body
) @handler_function

; ============================================
; Parameter Annotations
; ============================================

; @RequestBody request: CreateUserRequest
; @PathVariable id: Long
(parameter
  (modifiers
    (annotation
      (user_type
        (type_identifier) @param_annotation
        (#match? @param_annotation "^(RequestBody|PathVariable|RequestParam|RequestHeader)$")
      )
    )?
  )?
  name: (simple_identifier) @param_name
  type: (user_type) @param_type
) @annotated_param

; ============================================
; Data Classes
; ============================================

; data class UserDto(val name: String, val email: String?)
(class_declaration
  (modifiers
    (modifier) @data_modifier
    (#eq? @data_modifier "data")
  )
  name: (type_identifier) @data_class_name
  (primary_constructor
    (class_parameters
      (class_parameter
        (modifiers
          (modifier) @val_var
          (#match? @val_var "^(val|var)$")
        )?
        name: (simple_identifier) @property_name
        type: (user_type) @property_type
      )*
    )
  )
) @data_class

; ============================================
; Enum Classes
; ============================================

; enum class Status { ACTIVE, INACTIVE }
(class_declaration
  (modifiers
    (modifier) @enum_modifier
    (#eq? @enum_modifier "enum")
  )
  name: (type_identifier) @enum_name
  body: (enum_class_body
    (enum_entries
      (enum_entry
        name: (simple_identifier) @enum_value
      )*
    )
  )
) @enum_class

; ============================================
; Imports
; ============================================

; import org.springframework.web.bind.annotation.*
(import_header
  (identifier) @import_path
) @import_stmt
