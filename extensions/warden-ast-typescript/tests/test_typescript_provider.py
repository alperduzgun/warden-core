"""
Unit tests for TypeScript AST provider.
"""

import pytest
from warden_ast_typescript.provider import TypeScriptParserProvider
from warden.ast.domain.enums import CodeLanguage, ParseStatus, ASTNodeType


class TestProviderMetadata:
    """Test provider metadata and configuration."""

    def test_provider_name(self):
        """Test provider has correct name."""
        provider = TypeScriptParserProvider()
        assert provider.metadata.name == "typescript-parser"

    def test_provider_version(self):
        """Test provider has version."""
        provider = TypeScriptParserProvider()
        assert provider.metadata.version == "0.1.0"

    def test_supported_languages(self):
        """Test provider supports TypeScript."""
        provider = TypeScriptParserProvider()
        assert CodeLanguage.TYPESCRIPT in provider.metadata.supported_languages

    def test_supports_language_typescript(self):
        """Test supports_language returns True for TypeScript."""
        provider = TypeScriptParserProvider()
        assert provider.supports_language(CodeLanguage.TYPESCRIPT) is True

    def test_supports_language_other(self):
        """Test supports_language returns False for other languages."""
        provider = TypeScriptParserProvider()
        assert provider.supports_language(CodeLanguage.PYTHON) is False


class TestBasicParsing:
    """Test basic TypeScript parsing."""

    @pytest.mark.asyncio
    async def test_parse_simple_interface(self):
        """Test parsing a simple TypeScript interface."""
        provider = TypeScriptParserProvider()
        code = """
        interface User {
            name: string;
            age: number;
        }
        """

        result = await provider.parse(code, CodeLanguage.TYPESCRIPT, "User.ts")

        assert result.status == ParseStatus.SUCCESS
        assert result.ast_root is not None
        assert result.ast_root.node_type == ASTNodeType.MODULE

        # Find interface declaration
        interface_nodes = [
            node for node in result.ast_root.children if node.node_type == ASTNodeType.CLASS
        ]
        assert len(interface_nodes) == 1
        assert interface_nodes[0].name == "User"

    @pytest.mark.asyncio
    async def test_parse_simple_class(self):
        """Test parsing a simple TypeScript class."""
        provider = TypeScriptParserProvider()
        code = """
        class UserService {
            getUser(): void {
                return;
            }
        }
        """

        result = await provider.parse(code, CodeLanguage.TYPESCRIPT, "UserService.ts")

        assert result.status == ParseStatus.SUCCESS
        assert result.ast_root is not None

        # Find class declaration
        class_nodes = [
            node for node in result.ast_root.children if node.node_type == ASTNodeType.CLASS
        ]
        assert len(class_nodes) == 1
        assert class_nodes[0].name == "UserService"

    @pytest.mark.asyncio
    async def test_parse_function(self):
        """Test parsing a TypeScript function."""
        provider = TypeScriptParserProvider()
        code = """
        function calculateTotal(price: number, tax: number): number {
            return price + tax;
        }
        """

        result = await provider.parse(code, CodeLanguage.TYPESCRIPT, "calc.ts")

        assert result.status == ParseStatus.SUCCESS
        assert result.ast_root is not None

        # Find function declaration
        function_nodes = [
            node for node in result.ast_root.children if node.node_type == ASTNodeType.FUNCTION
        ]
        assert len(function_nodes) == 1
        assert function_nodes[0].name == "calculateTotal"

    @pytest.mark.asyncio
    async def test_parse_empty_code(self):
        """Test parsing empty code returns error."""
        provider = TypeScriptParserProvider()

        result = await provider.parse("", CodeLanguage.TYPESCRIPT, "empty.ts")

        assert result.status == ParseStatus.FAILED
        assert len(result.errors) > 0


class TestDecoratorParsing:
    """Test TypeScript decorator parsing."""

    @pytest.mark.asyncio
    async def test_parse_class_decorator(self):
        """Test parsing class with decorator."""
        provider = TypeScriptParserProvider()
        code = """
        @Component({
            selector: 'app-user',
            templateUrl: './user.component.html'
        })
        class UserComponent {
            name: string;
        }
        """

        result = await provider.parse(code, CodeLanguage.TYPESCRIPT, "user.component.ts")

        assert result.status == ParseStatus.SUCCESS

        # Find class with decorator
        class_nodes = [
            node for node in result.ast_root.children if node.node_type == ASTNodeType.CLASS
        ]
        assert len(class_nodes) == 1
        assert class_nodes[0].name == "UserComponent"
        assert "decorators" in class_nodes[0].attributes
        assert len(class_nodes[0].attributes["decorators"]) > 0

    @pytest.mark.asyncio
    async def test_parse_method_decorator(self):
        """Test parsing method with decorator."""
        provider = TypeScriptParserProvider()
        code = """
        class ApiService {
            @Get('/users')
            getUsers(): void {
                return;
            }
        }
        """

        result = await provider.parse(code, CodeLanguage.TYPESCRIPT, "api.service.ts")

        assert result.status == ParseStatus.SUCCESS

        # Find class
        class_nodes = [
            node for node in result.ast_root.children if node.node_type == ASTNodeType.CLASS
        ]
        assert len(class_nodes) == 1

        # Find method with decorator
        method_nodes = [
            node for node in class_nodes[0].children if node.node_type == ASTNodeType.FUNCTION
        ]
        assert len(method_nodes) == 1
        assert method_nodes[0].name == "getUsers"
        assert "decorators" in method_nodes[0].attributes


class TestModifierExtraction:
    """Test TypeScript modifier extraction."""

    @pytest.mark.asyncio
    async def test_parse_public_method(self):
        """Test parsing method with public modifier."""
        provider = TypeScriptParserProvider()
        code = """
        class UserService {
            public getUserName(): string {
                return "John";
            }
        }
        """

        result = await provider.parse(code, CodeLanguage.TYPESCRIPT, "UserService.ts")

        assert result.status == ParseStatus.SUCCESS

        # Find class
        class_nodes = [
            node for node in result.ast_root.children if node.node_type == ASTNodeType.CLASS
        ]
        assert len(class_nodes) == 1

        # Find method
        method_nodes = [
            node for node in class_nodes[0].children if node.node_type == ASTNodeType.FUNCTION
        ]
        assert len(method_nodes) == 1
        assert "modifiers" in method_nodes[0].attributes
        assert "public" in method_nodes[0].attributes["modifiers"]

    @pytest.mark.asyncio
    async def test_parse_async_function(self):
        """Test parsing async function."""
        provider = TypeScriptParserProvider()
        code = """
        async function fetchData(): Promise<void> {
            return;
        }
        """

        result = await provider.parse(code, CodeLanguage.TYPESCRIPT, "fetch.ts")

        assert result.status == ParseStatus.SUCCESS

        # Find function
        function_nodes = [
            node for node in result.ast_root.children if node.node_type == ASTNodeType.FUNCTION
        ]
        assert len(function_nodes) == 1
        assert "modifiers" in function_nodes[0].attributes
        assert "async" in function_nodes[0].attributes["modifiers"]
        assert function_nodes[0].attributes.get("async") is True


class TestGenericParsing:
    """Test TypeScript generics parsing."""

    @pytest.mark.asyncio
    async def test_parse_generic_interface(self):
        """Test parsing generic interface."""
        provider = TypeScriptParserProvider()
        code = """
        interface Repository<T> {
            findById(id: number): T;
        }
        """

        result = await provider.parse(code, CodeLanguage.TYPESCRIPT, "Repository.ts")

        assert result.status == ParseStatus.SUCCESS

        # Find interface
        interface_nodes = [
            node for node in result.ast_root.children if node.node_type == ASTNodeType.CLASS
        ]
        assert len(interface_nodes) == 1
        assert interface_nodes[0].name == "Repository"
        assert "generic" in interface_nodes[0].attributes
        assert interface_nodes[0].attributes["generic"] is True

    @pytest.mark.asyncio
    async def test_parse_generic_function(self):
        """Test parsing generic function."""
        provider = TypeScriptParserProvider()
        code = """
        function identity<T>(arg: T): T {
            return arg;
        }
        """

        result = await provider.parse(code, CodeLanguage.TYPESCRIPT, "utils.ts")

        assert result.status == ParseStatus.SUCCESS

        # Find function
        function_nodes = [
            node for node in result.ast_root.children if node.node_type == ASTNodeType.FUNCTION
        ]
        assert len(function_nodes) == 1
        assert function_nodes[0].name == "identity"
        assert "generic" in function_nodes[0].attributes


class TestImportExportParsing:
    """Test TypeScript import/export parsing."""

    @pytest.mark.asyncio
    async def test_parse_import_statement(self):
        """Test parsing import statement."""
        provider = TypeScriptParserProvider()
        code = """
        import { User, Product } from './models';
        """

        result = await provider.parse(code, CodeLanguage.TYPESCRIPT, "index.ts")

        assert result.status == ParseStatus.SUCCESS

        # Find import statement
        import_nodes = [
            node for node in result.ast_root.children if node.node_type == ASTNodeType.IMPORT
        ]
        assert len(import_nodes) == 1
        assert "module" in import_nodes[0].attributes
        assert import_nodes[0].attributes["module"] == "./models"

    @pytest.mark.asyncio
    async def test_parse_export_default(self):
        """Test parsing default export."""
        provider = TypeScriptParserProvider()
        code = """
        export default class User {
            name: string;
        }
        """

        result = await provider.parse(code, CodeLanguage.TYPESCRIPT, "User.ts")

        assert result.status == ParseStatus.SUCCESS

        # Find export statement
        export_nodes = [
            node for node in result.ast_root.children if node.node_type == ASTNodeType.IMPORT
        ]
        # Export statement wraps the class
        assert len(export_nodes) > 0


class TestTSXParsing:
    """Test TSX (TypeScript + JSX) parsing."""

    @pytest.mark.asyncio
    async def test_parse_tsx_component(self):
        """Test parsing TSX React component."""
        provider = TypeScriptParserProvider()
        code = """
        function UserCard({ name }: { name: string }) {
            return <div className="card">{name}</div>;
        }
        """

        result = await provider.parse(code, CodeLanguage.TYPESCRIPT, "UserCard.tsx")

        assert result.status == ParseStatus.SUCCESS

        # Find function component
        function_nodes = [
            node for node in result.ast_root.children if node.node_type == ASTNodeType.FUNCTION
        ]
        assert len(function_nodes) == 1
        assert function_nodes[0].name == "UserCard"

    @pytest.mark.asyncio
    async def test_parse_tsx_class_component(self):
        """Test parsing TSX class component."""
        provider = TypeScriptParserProvider()
        code = """
        class App extends Component {
            render() {
                return <h1>Hello</h1>;
            }
        }
        """

        result = await provider.parse(code, CodeLanguage.TYPESCRIPT, "App.tsx")

        assert result.status == ParseStatus.SUCCESS

        # Find class
        class_nodes = [
            node for node in result.ast_root.children if node.node_type == ASTNodeType.CLASS
        ]
        assert len(class_nodes) == 1
        assert class_nodes[0].name == "App"


class TestComplexCode:
    """Test parsing complex real-world TypeScript code."""

    @pytest.mark.asyncio
    async def test_parse_complex_service(self):
        """Test parsing complex service with multiple features."""
        provider = TypeScriptParserProvider()
        code = """
        import { Injectable } from '@nestjs/common';
        import { Repository } from 'typeorm';

        @Injectable()
        export class UserService {
            constructor(
                private readonly userRepository: Repository<User>
            ) {}

            async findById(id: number): Promise<User | null> {
                return this.userRepository.findOne({ where: { id } });
            }

            async create(userData: CreateUserDto): Promise<User> {
                const user = this.userRepository.create(userData);
                return this.userRepository.save(user);
            }
        }
        """

        result = await provider.parse(code, CodeLanguage.TYPESCRIPT, "user.service.ts")

        assert result.status == ParseStatus.SUCCESS
        assert result.ast_root is not None

        # Find imports
        import_nodes = [
            node for node in result.ast_root.children if node.node_type == ASTNodeType.IMPORT
        ]
        assert len(import_nodes) >= 2

        # Find class
        class_nodes = [
            node for node in result.ast_root.children
            if node.node_type == ASTNodeType.CLASS and node.name == "UserService"
        ]
        # Class might be wrapped in export_statement
        if len(class_nodes) == 0:
            # Check in export statement children
            for node in result.ast_root.children:
                if node.node_type == ASTNodeType.IMPORT:  # Export maps to IMPORT
                    for child in node.children:
                        if child.node_type == ASTNodeType.CLASS:
                            class_nodes.append(child)

        assert len(class_nodes) >= 1


class TestErrorHandling:
    """Test error handling."""

    @pytest.mark.asyncio
    async def test_parse_unsupported_language(self):
        """Test parsing with unsupported language returns error."""
        provider = TypeScriptParserProvider()

        result = await provider.parse(
            "const x = 1;",
            CodeLanguage.PYTHON,  # Wrong language
            "test.ts"
        )

        assert result.status == ParseStatus.UNSUPPORTED
        assert len(result.errors) > 0

    @pytest.mark.asyncio
    async def test_parse_without_validation(self):
        """Test parsing works without explicit validation call."""
        provider = TypeScriptParserProvider()
        code = "const x: number = 42;"

        result = await provider.parse(code, CodeLanguage.TYPESCRIPT, "test.ts")

        # Should auto-validate and parse successfully
        assert result.status == ParseStatus.SUCCESS
